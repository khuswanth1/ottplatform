import uuid
from datetime import datetime, timezone

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import audit, get_current_user
from .. import razorpay_client as razorpay
from .. import stripe_client as stripe
from ..models import LIVE_STATUSES, AuthSession, Subscription, User
from ..ratelimit import rate_limit
from ..schemas import ChangePasswordIn, DeleteAccountIn, Msg
from ..security import hash_password, validate_password_strength, verify_password
from ..useragent import describe
from .auth import _clear_cookies

log = logging.getLogger("account")
router = APIRouter(prefix="/account", tags=["account"])


class DeviceOut(BaseModel):
    id: uuid.UUID
    label: str
    ip: str | None = None
    created_at: datetime
    last_seen_at: datetime  # refreshed at most every 5 minutes, so it is a rough "last active"
    current: bool


def _open_sessions(user: User, now: datetime):
    return (AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > now)


@router.get("/devices", response_model=list[DeviceOut])
def devices(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every browser or device currently signed in to this account (one row per sign-in)."""
    now = datetime.now(timezone.utc)
    current = request.state.session.id
    rows = db.scalars(select(AuthSession).where(*_open_sessions(user, now)).order_by(AuthSession.last_seen_at.desc())).all()
    return [DeviceOut(id=r.id, label=describe(r.user_agent), ip=r.ip, created_at=r.created_at, last_seen_at=r.last_seen_at,
                      current=r.id == current) for r in rows]


@router.delete("/devices/{session_id}", response_model=Msg)
def sign_out_device(session_id: uuid.UUID, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Sign one other device out. Use /auth/logout for the device you are on."""
    if session_id == request.state.session.id:
        raise HTTPException(400, "That is this device. Use Sign out instead.")
    now = datetime.now(timezone.utc)
    row = db.scalar(select(AuthSession).where(AuthSession.id == session_id, *_open_sessions(user, now)))
    if not row:
        raise HTTPException(404, "Device not found.")  # also what someone else's id looks like
    row.revoked_at = now
    audit(db, request, user, "device_signed_out", "session", row.id)
    db.commit()
    return Msg(message="Signed out.")


@router.post("/sign-out-others", response_model=Msg)
def sign_out_others(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Sign out everywhere except the device making this request."""
    now = datetime.now(timezone.utc)
    result = db.execute(update(AuthSession).where(*_open_sessions(user, now), AuthSession.id != request.state.session.id)
                        .values(revoked_at=now).execution_options(synchronize_session=False))
    audit(db, request, user, "devices_signed_out", "user", user.id, {"count": result.rowcount})
    db.commit()
    return Msg(message=f"Signed out of {result.rowcount} other device{'s' if result.rowcount != 1 else ''}.")


@router.post("/change-password", response_model=Msg, dependencies=[Depends(rate_limit("change-password", 5, 60))])
def change_password(body: ChangePasswordIn, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Set a new password after proving the old one. Every other device is signed out; this one stays signed in."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(403, "That password is not correct.")
    if err := validate_password_strength(body.new_password):
        raise HTTPException(422, err)
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(422, "Choose a password you have not used for this account just now.")
    user.password_hash = hash_password(body.new_password)
    now = datetime.now(timezone.utc)
    db.execute(update(AuthSession).where(*_open_sessions(user, now), AuthSession.id != request.state.session.id)
               .values(revoked_at=now).execution_options(synchronize_session=False))
    audit(db, request, user, "password.changed", "user", user.id)
    db.commit()
    return Msg(message="Password updated. Your other devices were signed out.")


@router.post("/delete", response_model=Msg, dependencies=[Depends(rate_limit("account-delete", 5, 60))])
def delete_account(body: DeleteAccountIn, request: Request, response: Response, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Permanently delete the account and everything under it (profiles, lists, history, ratings, reminders, notifications,
    sign-ins, subscription records). Needs the password. A live paid plan is ended at the payment provider first; if that fails
    nothing is deleted, so no one is left paying for an account that is gone. Stripe keeps its own invoices for tax law."""
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(403, "That password is not correct.")
    if user.role == "admin" and not db.scalar(select(User.id).where(User.role == "admin", User.id != user.id, User.is_active.is_(True)).limit(1)):
        raise HTTPException(409, "You are the only administrator. Make someone else an administrator first.")
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id, Subscription.status.in_(LIVE_STATUSES)))
    if sub and sub.provider == "razorpay" and sub.razorpay_subscription_id and razorpay.enabled():
        try:
            razorpay.cancel_subscription(sub.razorpay_subscription_id, at_cycle_end=False)
        except razorpay.RazorpayError as e:
            log.warning("account delete: cancelling the razorpay subscription failed user=%s: %s", user.id, e)
            raise HTTPException(502, "We could not end your paid plan right now, so nothing was deleted. Please try again in a moment.")
    if sub and sub.provider == "stripe" and sub.stripe_subscription_id and stripe.enabled():
        try:
            stripe.cancel_subscription_now(sub.stripe_subscription_id)
        except stripe.StripeError as e:
            log.warning("account delete: cancelling the subscription failed user=%s: %s", user.id, e)
            raise HTTPException(502, "We could not end your paid plan right now, so nothing was deleted. Please try again in a moment.")
    audit(db, request, user, "account.deleted", "user", user.id)  # the actor link is cleared when the user row goes
    db.delete(user)
    db.commit()
    _clear_cookies(response)
    return Msg(message="Your account has been deleted.")
