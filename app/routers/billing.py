"""Plans, Stripe Checkout and the account's subscription state.

Stripe is the source of truth for money; this API only mirrors what the signed webhook tells it. The browser's
"success" redirect is never trusted: the plan changes only when a verified event arrives."""
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import razorpay_client as razorpay
from .. import stripe_client as stripe
from ..config import get_settings
from ..db import get_db
from ..deps import require_verified, resolve_country
from ..models import LIVE_STATUSES, Plan, PlanPrice, StripeEvent, Subscription, User
from ..ratelimit import rate_limit
from ..schemas import (
    ChangePlanIn, CheckoutIn, InvoiceOut, Msg, PlanOut, PlansOut, RazorpaySubscribeIn, RazorpaySubscribeOut,
    RazorpayOrderOut, RazorpayOrderVerifyIn, RazorpayVerifyIn, SubscriptionOut, UrlOut,
)

log = logging.getLogger("billing")
router = APIRouter(prefix="/billing", tags=["billing"])

_STATUS = {"active": "active", "trialing": "trialing", "past_due": "past_due", "unpaid": "expired",
           "canceled": "cancelled", "incomplete_expired": "expired", "paused": "expired"}  # "incomplete" is ignored


def _price(db: Session, plan: Plan, country: str) -> PlanPrice | None:
    rows = {p.country: p for p in db.scalars(select(PlanPrice).where(PlanPrice.plan_id == plan.id))}
    return rows.get(country) or rows.get("*")


def _live(db: Session, user_id) -> Subscription | None:
    return db.scalar(select(Subscription).where(Subscription.user_id == user_id,
                                                Subscription.status.in_(LIVE_STATUSES)))


def _latest(db: Session, user_id) -> Subscription | None:
    return db.scalar(select(Subscription).where(Subscription.user_id == user_id)
                     .order_by(Subscription.created_at.desc()).limit(1))


@router.get("/plans", response_model=PlansOut)
def plans(request: Request, db: Session = Depends(get_db)):
    country = resolve_country(request)
    out = []
    for p in db.scalars(select(Plan).order_by(Plan.sort)):
        price = _price(db, p, country) if p.code != "free" else None
        providers = []
        if price and p.code != "free":
            if stripe.enabled() and price.stripe_price_id:
                providers.append("stripe")
            if razorpay.enabled() and price.razorpay_plan_id:
                providers.append("razorpay")  # AutoPay (cards, eMandate)
            if razorpay.enabled() and price.currency == "INR":
                providers.append("razorpay_once")  # pay once: UPI, cards, net banking, wallets
        out.append(PlanOut(
            code=p.code, name=p.name, has_ads=p.has_ads, premium_titles=p.entitlement == "premium", max_streams=p.max_streams,
            price={"currency": price.currency, "amount_cents": price.amount_cents} if price else None,
            purchasable=bool(providers), providers=providers))
    return PlansOut(enabled=stripe.enabled() or razorpay.enabled(), plans=out,
                    razorpay_key_id=get_settings().razorpay_key_id if razorpay.enabled() else None)


@router.get("/subscription", response_model=SubscriptionOut)
def subscription(user: User = Depends(require_verified), db: Session = Depends(get_db)):
    expire_prepaid(db, user.id)
    sub = _live(db, user.id) or _latest(db, user.id)
    if not sub:
        free = db.scalar(select(Plan).where(Plan.code == "free"))
        return SubscriptionOut(plan_code="free", plan_name=free.name if free else "Free", status="none")
    live = sub.status in LIVE_STATUSES
    free = None if live else db.scalar(select(Plan).where(Plan.code == "free"))
    return SubscriptionOut(
        plan_code=sub.plan.code if live else "free", plan_name=sub.plan.name if live else (free.name if free else "Free"),
        status=sub.status, current_period_end=sub.current_period_end, cancel_at_period_end=sub.cancel_at_period_end,
        can_manage=bool(sub.provider == "stripe" and sub.stripe_customer_id and stripe.enabled()))


@router.post("/checkout", response_model=UrlOut, dependencies=[Depends(rate_limit("billing", 20, 60))])
def checkout(body: CheckoutIn, request: Request, user: User = Depends(require_verified), db: Session = Depends(get_db)):
    expire_prepaid(db, user.id)
    if not stripe.enabled():
        raise HTTPException(503, "Paid plans are not available right now.")
    plan = db.scalar(select(Plan).where(Plan.code == body.plan_code))
    price = _price(db, plan, resolve_country(request)) if plan else None
    if not price or not price.stripe_price_id:
        raise HTTPException(400, "That plan is not available in your region.")
    if _live(db, user.id):
        raise HTTPException(409, "You already have a plan. Use Manage billing to change or cancel it.")
    prev = _latest(db, user.id)
    base = get_settings().frontend_url.rstrip("/")
    try:
        sess = stripe.create_checkout_session(
            price_id=price.stripe_price_id, user_id=str(user.id), email=user.email, plan_code=plan.code,
            success_url=f"{base}/account?checkout=success", cancel_url=f"{base}/plans?checkout=cancelled",
            customer_id=prev.stripe_customer_id if prev and prev.provider == "stripe" else None)
    except stripe.StripeError as e:
        log.warning("checkout failed user=%s: %s", user.id, e)
        raise HTTPException(502, "Could not start checkout. Please try again.")
    if not sess.get("url"):
        raise HTTPException(502, "Could not start checkout. Please try again.")
    return UrlOut(url=sess["url"])


@router.post("/portal", response_model=UrlOut, dependencies=[Depends(rate_limit("billing", 20, 60))])
def portal(user: User = Depends(require_verified), db: Session = Depends(get_db)):
    sub = _latest(db, user.id)
    if not stripe.enabled() or not sub or sub.provider != "stripe" or not sub.stripe_customer_id:
        raise HTTPException(409, "There is no billing account to manage.")
    try:
        sess = stripe.create_portal_session(customer_id=sub.stripe_customer_id,
                                            return_url=get_settings().frontend_url.rstrip("/") + "/account")
    except stripe.StripeError as e:
        log.warning("portal failed user=%s: %s", user.id, e)
        raise HTTPException(502, "Could not open billing. Please try again.")
    return UrlOut(url=sess["url"])


# ------------------------------------------------------------------ change, cancel, invoices
def _own_live_subscription(db: Session, user: User, *, lock: bool = False) -> Subscription:
    stmt = select(Subscription).where(Subscription.user_id == user.id, Subscription.status.in_(LIVE_STATUSES))
    sub = db.scalar(stmt.with_for_update() if lock else stmt)  # lock: two quick clicks must not both call the gateway
    if not sub:
        raise HTTPException(409, "You do not have a plan to change.")
    if sub.provider == "razorpay":
        if not sub.razorpay_subscription_id:
            raise HTTPException(409, "This plan was paid once and simply ends on its date. Nothing renews, so there is nothing to cancel.")
        if not razorpay.enabled():
            raise HTTPException(409, "You do not have a plan to change.")
    elif not stripe.enabled() or not sub.stripe_subscription_id:
        raise HTTPException(409, "You do not have a plan to change.")
    return sub


def _stripe_call(fn, what: str, user_id, message: str | None = None):
    try:
        return fn()
    except (stripe.StripeError, razorpay.RazorpayError) as e:
        log.warning("%s failed user=%s: %s", what, user_id, e)
        raise HTTPException(502, message or "The payment provider could not do that right now. Nothing was changed. Please try again.")


@router.post("/change-plan", response_model=Msg, dependencies=[Depends(rate_limit("billing", 20, 60))])
def change_plan(body: ChangePlanIn, request: Request, user: User = Depends(require_verified), db: Session = Depends(get_db)):
    """Switch the live subscription to another paid plan, effective now with proration (see the build log: no scheduled
    downgrades). The plan shown in the app updates when Stripe's webhook arrives, usually within seconds."""
    sub = _own_live_subscription(db, user, lock=True)
    if sub.provider == "razorpay":
        raise HTTPException(409, "To switch plans, let this one end (or cancel AutoPay) and choose the new plan after it ends.")
    if sub.plan.code == body.plan_code:
        raise HTTPException(409, "You are already on that plan.")
    plan = db.scalar(select(Plan).where(Plan.code == body.plan_code))
    price = _price(db, plan, resolve_country(request)) if plan else None
    if not price or not price.stripe_price_id:
        raise HTTPException(400, "That plan is not available in your region.")
    _stripe_call(lambda: stripe.switch_subscription_price(subscription_id=sub.stripe_subscription_id,
                                                          price_id=price.stripe_price_id, plan_code=plan.code),
                 "change-plan", user.id)
    return Msg(message="Plan change requested. It will show here in a few seconds.")


@router.post("/cancel", response_model=Msg, dependencies=[Depends(rate_limit("billing", 20, 60))])
def cancel(user: User = Depends(require_verified), db: Session = Depends(get_db)):
    """Stop renewing at the end of the paid period. Access continues until then."""
    sub = _own_live_subscription(db, user, lock=True)
    if sub.provider == "razorpay":
        _stripe_call(lambda: razorpay.cancel_subscription(sub.razorpay_subscription_id, at_cycle_end=True), "cancel", user.id)
        sub.cancel_at_period_end = True  # mirrored now for the UI; Razorpay's webhook confirms and later ends the plan
        db.commit()
        return Msg(message="AutoPay will stop at the end of the period you paid for. Your plan keeps working until then.")
    _stripe_call(lambda: stripe.set_cancel_at_period_end(subscription_id=sub.stripe_subscription_id, cancel=True),
                 "cancel", user.id)
    return Msg(message="Cancellation requested. Your plan keeps working until the end of the period you paid for.")


@router.post("/resume", response_model=Msg, dependencies=[Depends(rate_limit("billing", 20, 60))])
def resume(user: User = Depends(require_verified), db: Session = Depends(get_db)):
    """Undo a pending cancellation."""
    sub = _own_live_subscription(db, user, lock=True)
    if sub.provider == "razorpay":
        _stripe_call(lambda: razorpay.keep_subscription(sub.razorpay_subscription_id), "resume", user.id)
        sub.cancel_at_period_end = False
        db.commit()
        return Msg(message="AutoPay will continue as usual.")
    _stripe_call(lambda: stripe.set_cancel_at_period_end(subscription_id=sub.stripe_subscription_id, cancel=False),
                 "resume", user.id)
    return Msg(message="Your plan will renew as usual.")


@router.get("/invoices", response_model=list[InvoiceOut], dependencies=[Depends(rate_limit("billing", 20, 60))])
def invoices(user: User = Depends(require_verified), db: Session = Depends(get_db)):
    """Recent invoices, read from Stripe on request (nothing is stored here). Empty when there is no billing account."""
    sub = _latest(db, user.id)
    if not stripe.enabled() or not sub or sub.provider != "stripe" or not sub.stripe_customer_id:
        return []
    rows = _stripe_call(lambda: stripe.list_invoices(customer_id=sub.stripe_customer_id), "invoices", user.id,
                        "Could not load your invoices right now. Please try again in a moment.")
    out = []
    for r in rows:
        url = r.get("hosted_invoice_url")
        out.append(InvoiceOut(
            id=r["id"], number=r.get("number"), created=datetime.fromtimestamp(r.get("created", 0), tz=timezone.utc),
            total_cents=int(r.get("total", 0)), currency=(r.get("currency") or "usd").upper(), status=r.get("status") or "draft",
            url=url if isinstance(url, str) and url.startswith("https://") else None))
    return out


# ------------------------------------------------------------------ Razorpay AutoPay
PREPAID_DAYS = 30
_RZP_STATUS = {"authenticated": "active", "active": "active", "pending": "past_due", "halted": "expired",
               "cancelled": "cancelled", "completed": "expired", "expired": "expired", "paused": "expired"}  # "created": ignored


def _rzp_notes(ent: dict) -> dict:
    n = ent.get("notes")
    return n if isinstance(n, dict) else {}  # Razorpay sends [] when there are no notes


def _apply_razorpay(db: Session, ent: dict, created: int) -> str | None:
    """Mirrors a Razorpay subscription entity locally. Returns an error string when it cannot be applied."""
    status = _RZP_STATUS.get(ent.get("status", ""))
    if not status:
        return None  # created: the customer has not authorised yet
    sid = ent["id"]
    sub = db.scalar(select(Subscription).where(Subscription.razorpay_subscription_id == sid))
    pp = db.scalar(select(PlanPrice).where(PlanPrice.razorpay_plan_id == ent.get("plan_id")).limit(1))
    plan = db.get(Plan, pp.plan_id) if pp else None
    if not plan:
        return f"no plan matches razorpay subscription {sid}"
    if sub and sub.event_ts > created:
        return None  # an older event that arrived late
    user = db.get(User, sub.user_id) if sub else _user(db, _rzp_notes(ent).get("user_id"))
    if not user:
        return f"no user for razorpay subscription {sid}"
    if not sub:
        sub = Subscription(user_id=user.id, plan_id=plan.id, status=status, provider="razorpay", razorpay_subscription_id=sid)
        db.add(sub)
    end = ent.get("current_end")
    sub.plan_id, sub.status, sub.event_ts = plan.id, status, created
    sub.current_period_end = datetime.fromtimestamp(end, tz=timezone.utc) if end else sub.current_period_end
    sub.cancel_at_period_end = bool(ent.get("has_scheduled_changes")) and status == "active"
    db.flush()
    db.refresh(sub)
    _sync_user_plan(db, user)
    return None


@router.post("/razorpay/subscribe", response_model=RazorpaySubscribeOut, dependencies=[Depends(rate_limit("billing", 20, 60))])
def razorpay_subscribe(body: RazorpaySubscribeIn, request: Request, user: User = Depends(require_verified),
                       db: Session = Depends(get_db)):
    """Step 1 of AutoPay: creates the recurring subscription at Razorpay and returns what Checkout needs to open.
    Nothing is charged and no plan is granted here."""
    expire_prepaid(db, user.id)
    if not razorpay.enabled():
        raise HTTPException(503, "Paid plans are not available right now.")
    plan = db.scalar(select(Plan).where(Plan.code == body.plan_code))
    price = _price(db, plan, resolve_country(request)) if plan else None
    if not price or not price.razorpay_plan_id:
        raise HTTPException(400, "That plan is not available with Razorpay in your region.")
    if _live(db, user.id):
        raise HTTPException(409, "You already have a plan. Use your account page to change or cancel it.")
    try:
        sub = razorpay.create_subscription(plan_id=price.razorpay_plan_id, user_id=str(user.id), plan_code=plan.code)
    except razorpay.RazorpayError as e:
        log.warning("razorpay subscribe failed user=%s: %s", user.id, e)
        raise HTTPException(502, "Could not start checkout. Please try again.")
    return RazorpaySubscribeOut(subscription_id=sub["id"], key_id=get_settings().razorpay_key_id, name="CineVerse",
                                email=user.email)


@router.post("/razorpay/verify", response_model=Msg, dependencies=[Depends(rate_limit("billing", 20, 60))])
def razorpay_verify(body: RazorpayVerifyIn, user: User = Depends(require_verified), db: Session = Depends(get_db)):
    """Step 2: after Checkout. The browser's word is not enough: the HMAC signature must match our secret AND the
    subscription is re-read from Razorpay, must belong to this user, and must be authorised/active there."""
    if not razorpay.enabled():
        raise HTTPException(503, "Paid plans are not available right now.")
    if not razorpay.verify_checkout_signature(body.razorpay_payment_id, body.razorpay_subscription_id, body.razorpay_signature):
        raise HTTPException(400, "Payment could not be verified.")
    try:
        ent = razorpay.retrieve_subscription(body.razorpay_subscription_id)
    except razorpay.RazorpayError as e:
        log.warning("razorpay verify failed user=%s: %s", user.id, e)
        raise HTTPException(502, "Could not confirm the payment right now. If you were charged it will appear shortly.")
    if _rzp_notes(ent).get("user_id") != str(user.id):
        raise HTTPException(403, "That subscription does not belong to this account.")
    try:
        err = _apply_razorpay(db, ent, int(time.time()))
        if err:
            db.rollback()
            log.error("razorpay verify user=%s: %s", user.id, err)
            raise HTTPException(409, "That plan could not be activated. Please contact support.")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You already have a plan.")
    return Msg(message="AutoPay is set up. Your plan is active.")


@router.post("/razorpay/order", response_model=RazorpayOrderOut, dependencies=[Depends(rate_limit("billing", 20, 60))])
def razorpay_order(body: RazorpaySubscribeIn, request: Request, user: User = Depends(require_verified),
                   db: Session = Depends(get_db)):
    """Pay once for PREPAID_DAYS of a plan with any method Razorpay offers (UPI, cards, net banking). The amount always comes
    from our price table, never from the browser. Nothing is granted until the payment is verified."""
    expire_prepaid(db, user.id)
    if not razorpay.enabled():
        raise HTTPException(503, "Paid plans are not available right now.")
    plan = db.scalar(select(Plan).where(Plan.code == body.plan_code))
    price = _price(db, plan, resolve_country(request)) if plan else None
    if not price or price.currency != "INR":
        raise HTTPException(400, "One-time payment is available for plans priced in INR.")
    if _live(db, user.id):
        raise HTTPException(409, "You already have a plan. Use your account page to change or cancel it.")
    try:
        order = razorpay.create_order(amount_paise=price.amount_cents, currency=price.currency,
                                      receipt=f"{plan.code}-{uuid.uuid4().hex[:12]}", user_id=str(user.id), plan_code=plan.code)
    except razorpay.RazorpayError as e:
        log.warning("razorpay order failed user=%s: %s", user.id, e)
        raise HTTPException(502, "Could not start checkout. Please try again.")
    return RazorpayOrderOut(order_id=order["id"], amount=price.amount_cents, currency=price.currency,
                            key_id=get_settings().razorpay_key_id, name="CineVerse", email=user.email)


@router.post("/razorpay/verify-order", response_model=Msg, dependencies=[Depends(rate_limit("billing", 20, 60))])
def razorpay_verify_order(body: RazorpayOrderVerifyIn, user: User = Depends(require_verified), db: Session = Depends(get_db)):
    """Grants PREPAID_DAYS only when: the signature is genuine, the order re-read from Razorpay is fully paid, belongs to this
    user and was created for a plan we price. Replaying the same payment id changes nothing."""
    if not razorpay.enabled():
        raise HTTPException(503, "Paid plans are not available right now.")
    if not razorpay.verify_order_signature(body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature):
        raise HTTPException(400, "Payment could not be verified.")
    if db.scalar(select(Subscription.id).where(Subscription.razorpay_payment_id == body.razorpay_payment_id)):
        return Msg(message="Your plan is active.")  # already applied: idempotent
    try:
        order = razorpay.retrieve_order(body.razorpay_order_id)
    except razorpay.RazorpayError as e:
        log.warning("razorpay verify-order failed user=%s: %s", user.id, e)
        raise HTTPException(502, "Could not confirm the payment right now. If you were charged it will appear shortly.")
    notes = _rzp_notes(order)
    if notes.get("user_id") != str(user.id):
        raise HTTPException(403, "That payment does not belong to this account.")
    plan = db.scalar(select(Plan).where(Plan.code == notes.get("plan_code")))
    pp = db.scalar(select(PlanPrice).where(PlanPrice.plan_id == plan.id, PlanPrice.currency == order.get("currency"),
                                           PlanPrice.amount_cents == order.get("amount")).limit(1)) if plan else None
    if not pp or order.get("status") != "paid" or order.get("amount_paid") != order.get("amount"):
        raise HTTPException(409, "That payment is not complete, so no plan was activated.")
    if _live(db, user.id):
        raise HTTPException(409, "You already have a plan.")
    now = datetime.now(timezone.utc)
    db.add(Subscription(user_id=user.id, plan_id=plan.id, status="active", provider="razorpay",
                        razorpay_payment_id=body.razorpay_payment_id, event_ts=int(now.timestamp()),
                        current_period_end=now + timedelta(days=PREPAID_DAYS)))
    try:
        db.flush()
        _sync_user_plan(db, user)
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.scalar(select(Subscription.id).where(Subscription.razorpay_payment_id == body.razorpay_payment_id)):
            return Msg(message="Your plan is active.")  # a concurrent identical request won
        raise HTTPException(409, "You already have a plan.")
    return Msg(message=f"Payment received. Your plan is active for {PREPAID_DAYS} days.")


def expire_prepaid(db: Session, user_id=None) -> int:
    """Ends one-time purchases whose paid period is over and refreshes the cached users.plan. Run by the worker every few
    minutes and before a user's own billing reads. Returns how many were ended."""
    now = datetime.now(timezone.utc)
    stmt = select(Subscription).where(Subscription.provider == "razorpay", Subscription.razorpay_subscription_id.is_(None),
                                      Subscription.status.in_(LIVE_STATUSES), Subscription.current_period_end < now)
    if user_id:
        stmt = stmt.where(Subscription.user_id == user_id)
    rows = db.scalars(stmt).all()
    for sub in rows:
        sub.status = "expired"
    db.flush()
    for uid in {r.user_id for r in rows}:
        if u := db.get(User, uid):
            _sync_user_plan(db, u)
    db.commit()
    return len(rows)


@router.post("/razorpay/webhook", include_in_schema=False)
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    payload = await request.body()
    if not razorpay.verify_webhook_signature(payload, request.headers.get("x-razorpay-signature"), s.razorpay_webhook_secret):
        raise HTTPException(400, "Invalid signature.")
    try:
        event = json.loads(payload)
        etype, ent = event["event"], event["payload"]["subscription"]["entity"]
        created = int(event.get("created_at", 0))
    except (ValueError, KeyError, TypeError):
        return {"received": True, "ignored": True}  # a valid signature on an event we do not handle (payments, invoices...)
    eid = "rzp:" + (request.headers.get("x-razorpay-event-id") or hashlib.sha256(payload).hexdigest()[:40])
    db.add(StripeEvent(id=eid, type=etype[:64]))  # same idempotency table: the id is the primary key
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"received": True, "duplicate": True}
    try:
        err = _apply_razorpay(db, ent, created) if etype.startswith("subscription.") else None
        if err:
            db.get(StripeEvent, eid).error = err
            log.error("razorpay event %s (%s): %s", eid, etype, err)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        db.add(StripeEvent(id=eid, type=etype[:64], error=f"integrity error: {e.orig}"))
        db.commit()
        log.error("razorpay event %s (%s) violated a constraint: %s", eid, etype, e.orig)
    except Exception:
        db.rollback()
        log.exception("razorpay event %s (%s) failed", eid, etype)
        return JSONResponse({"detail": "Processing failed."}, status_code=500)
    return {"received": True}


# ------------------------------------------------------------------ webhook
def _sync_user_plan(db: Session, user: User) -> None:
    """users.plan is a cached copy of what the live subscription entitles: only the webhook writes it for paying users."""
    live = _live(db, user.id)
    user.plan = "premium" if live and live.plan.entitlement == "premium" else "free"


def _plan_for(db: Session, obj: dict) -> Plan | None:
    items = ((obj.get("items") or {}).get("data")) or []
    price_id = ((items[0].get("price") or {}).get("id")) if items else None
    if price_id:
        pp = db.scalar(select(PlanPrice).where(PlanPrice.stripe_price_id == price_id).limit(1))
        if pp:
            return db.get(Plan, pp.plan_id)
    code = (obj.get("metadata") or {}).get("plan_code")
    return db.scalar(select(Plan).where(Plan.code == code)) if code else None


def _user(db: Session, raw) -> User | None:
    try:
        return db.get(User, uuid.UUID(str(raw))) if raw else None
    except ValueError:
        return None


def _period_end(obj: dict) -> datetime | None:
    items = ((obj.get("items") or {}).get("data")) or []
    ts = obj.get("current_period_end") or (items[0].get("current_period_end") if items else None)
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


def _apply_subscription(db: Session, obj: dict, created: int) -> str | None:
    """Returns an error string when the event cannot be applied (recorded, not retried)."""
    status = _STATUS.get(obj.get("status", ""))
    if not status:
        return None  # incomplete checkout: nothing to mirror yet
    sub = db.scalar(select(Subscription).where(Subscription.stripe_subscription_id == obj["id"]))
    plan = _plan_for(db, obj)
    if not plan:
        return f"no plan matches subscription {obj['id']}"
    if sub and sub.event_ts > created:
        return None  # an older event that arrived late
    user = db.get(User, sub.user_id) if sub else _user(db, (obj.get("metadata") or {}).get("user_id"))
    if not user:
        return f"no user for subscription {obj['id']}"
    if not sub:
        sub = Subscription(user_id=user.id, plan_id=plan.id, status=status, stripe_customer_id=obj["customer"],
                           stripe_subscription_id=obj["id"])
        db.add(sub)
    sub.plan_id, sub.status, sub.event_ts = plan.id, status, created
    sub.stripe_customer_id = obj.get("customer") or sub.stripe_customer_id
    # the customer portal may schedule the end with cancel_at instead of the cancel_at_period_end flag
    sub.current_period_end, sub.cancel_at_period_end = _period_end(obj), bool(obj.get("cancel_at_period_end") or obj.get("cancel_at"))
    db.flush()
    db.refresh(sub)
    _sync_user_plan(db, user)
    return None


def _apply_checkout(db: Session, obj: dict, created: int) -> str | None:
    """Links user, customer and subscription as soon as the payment page completes; subscription.* events then refine it."""
    if obj.get("mode") != "subscription" or not obj.get("subscription"):
        return None
    if db.scalar(select(Subscription.id).where(Subscription.stripe_subscription_id == obj["subscription"])):
        return None
    uid, code = obj.get("client_reference_id"), (obj.get("metadata") or {}).get("plan_code")
    plan = db.scalar(select(Plan).where(Plan.code == code)) if code else None
    user = _user(db, uid)
    if not user or not plan:
        return "checkout session without a known user or plan"
    if obj.get("payment_status") not in ("paid", "no_payment_required"):
        return None  # wait for the subscription events
    db.add(Subscription(user_id=user.id, plan_id=plan.id, status="active", stripe_customer_id=obj["customer"],
                        stripe_subscription_id=obj["subscription"], event_ts=created))
    db.flush()
    _sync_user_plan(db, user)
    return None


@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    payload = await request.body()
    if not stripe.verify_signature(payload, request.headers.get("stripe-signature"), s.stripe_webhook_secret,
                                   s.stripe_webhook_tolerance_s):
        raise HTTPException(400, "Invalid signature.")
    try:
        event = json.loads(payload)
        eid, etype, created, obj = event["id"], event["type"], int(event.get("created", 0)), event["data"]["object"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "Malformed event.")
    # Insert the event id first and apply its effects in the same transaction: a replay hits the primary key and is
    # acknowledged without work; a crash rolls both back so Stripe's retry processes it again.
    db.add(StripeEvent(id=eid, type=etype))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"received": True, "duplicate": True}
    try:
        err = None
        if etype in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
            err = _apply_subscription(db, obj, created)
        elif etype == "checkout.session.completed":
            err = _apply_checkout(db, obj, created)
        if err:
            db.get(StripeEvent, eid).error = err
            log.error("stripe event %s (%s): %s", eid, etype, err)
        db.commit()
    except IntegrityError as e:  # e.g. a second live subscription for one user: needs a human, so record and acknowledge
        db.rollback()
        db.add(StripeEvent(id=eid, type=etype, error=f"integrity error: {e.orig}"))
        db.commit()
        log.error("stripe event %s (%s) violated a constraint: %s", eid, etype, e.orig)
    except Exception:
        db.rollback()
        log.exception("stripe event %s (%s) failed", eid, etype)
        return JSONResponse({"detail": "Processing failed."}, status_code=500)
    return {"received": True}
