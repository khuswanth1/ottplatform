import json
import time

import httpx
import pytest

from app import razorpay_client as rz
from app.config import get_settings
from app.models import Plan, PlanPrice, StripeEvent, Subscription, User

KEY_SECRET, WH_SECRET = "test_key_secret", "test_webhook_secret"


@pytest.fixture(autouse=True)
def rzp(monkeypatch, db):
    s = get_settings()
    monkeypatch.setattr(s, "razorpay_key_id", "rzp_test_abc")
    monkeypatch.setattr(s, "razorpay_key_secret", KEY_SECRET)
    monkeypatch.setattr(s, "razorpay_webhook_secret", WH_SECRET)
    st = {"calls": [], "entity": {}, "order": {}, "fail": False}

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else None
        st["calls"].append((req.method, req.url.path, body))
        if st["fail"]:
            return httpx.Response(400, json={"error": {"description": "Gateway says no"}})
        if req.method == "POST" and req.url.path.endswith("/orders"):
            return httpx.Response(200, json={"id": "order_O1", "status": "created", **body})
        if req.method == "GET" and "/orders/" in req.url.path:
            return httpx.Response(200, json=st["order"])
        if req.method == "POST" and req.url.path.endswith("/subscriptions"):
            return httpx.Response(200, json={"id": "sub_R1", "status": "created", "plan_id": body["plan_id"], "notes": body["notes"]})
        if req.method == "GET" and "/subscriptions/" in req.url.path:
            return httpx.Response(200, json=st["entity"])
        return httpx.Response(200, json={"id": "sub_R1", "status": "active"})

    monkeypatch.setattr(rz, "_transport", httpx.MockTransport(handler))
    db.add_all([Plan(code=c, name=n, has_ads=a, entitlement=e, sort=i, max_streams=2) for i, (c, n, a, e) in enumerate([
        ("free", "Free", False, "registered"), ("ads", "With ads", True, "registered"),
        ("standard", "Standard", False, "premium"), ("premium", "Premium", False, "premium")])])
    db.commit()
    p = db.query(Plan).filter_by(code="standard").one()
    db.add(PlanPrice(plan_id=p.id, country="*", currency="INR", amount_cents=19900, razorpay_plan_id="plan_STD"))
    db.commit()
    return st


def uid(db, email="user@example.com"):
    return str(db.query(User).filter_by(email=email).one().id)


def entity(user_id, status="active", **kw):
    return {"id": "sub_R1", "plan_id": "plan_STD", "status": status, "current_end": 1900000000,
            "notes": {"user_id": user_id, "plan_code": "standard"}, **kw}


def verify_body(sid="sub_R1", pay="pay_1", secret=KEY_SECRET):
    return {"razorpay_payment_id": pay, "razorpay_subscription_id": sid,
            "razorpay_signature": rz.sign_checkout(pay, sid, secret)}


def hook(b, event, ent, eid="evt_1", created=None, secret=WH_SECRET):
    body = json.dumps({"event": event, "created_at": created or int(time.time()),
                       "payload": {"subscription": {"entity": ent}}}).encode()
    return b.c.post("/api/v1/billing/razorpay/webhook", content=body,
                    headers={"x-razorpay-signature": rz.sign_webhook(body, secret), "x-razorpay-event-id": eid})


def test_plans_advertise_each_gateway_only_when_it_can_sell(make_user, db):
    b = make_user()
    r = b.get("/billing/plans").json()
    std = next(p for p in r["plans"] if p["code"] == "standard")
    ads = next(p for p in r["plans"] if p["code"] == "ads")
    assert r["enabled"] and r["razorpay_key_id"] == "rzp_test_abc" and "secret" not in json.dumps(r).lower()
    assert std["providers"] == ["razorpay", "razorpay_once"] and std["purchasable"] and std["price"]["currency"] == "INR"
    assert ads["providers"] == [] and not ads["purchasable"]  # no price row at all


def test_subscribe_creates_a_recurring_mandate_and_grants_nothing(make_user, db, rzp):
    b = make_user()
    r = b.post("/billing/razorpay/subscribe", json={"plan_code": "standard"})
    assert r.status_code == 200 and r.json()["subscription_id"] == "sub_R1" and r.json()["key_id"] == "rzp_test_abc"
    method, path, body = rzp["calls"][0]
    assert path.endswith("/subscriptions") and body["plan_id"] == "plan_STD" and body["total_count"] > 1
    assert body["notes"]["user_id"] == uid(db)
    assert db.query(Subscription).count() == 0 and db.query(User).one().plan == "free"
    assert b.post("/billing/razorpay/subscribe", json={"plan_code": "premium"}).status_code == 400  # no Razorpay plan


def test_subscribe_requires_sign_in_and_blocks_double_subscriptions(make_user, db, rzp):
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).post("/api/v1/billing/razorpay/subscribe", json={"plan_code": "standard"}).status_code in (401, 403)
    b = make_user()
    rzp["entity"] = entity(uid(db))
    assert b.post("/billing/razorpay/verify", json=verify_body()).status_code == 200
    assert b.post("/billing/razorpay/subscribe", json={"plan_code": "standard"}).status_code == 409


def test_verify_activates_only_with_a_genuine_signature_and_gateway_state(make_user, db, rzp):
    b = make_user()
    rzp["entity"] = entity(uid(db), status="authenticated")
    bad = verify_body(secret="wrong")
    assert b.post("/billing/razorpay/verify", json=bad).status_code == 400  # forged signature
    assert db.query(Subscription).count() == 0 and db.query(User).one().plan == "free"
    ok = b.post("/billing/razorpay/verify", json=verify_body())
    assert ok.status_code == 200
    sub = db.query(Subscription).one()
    assert (sub.provider, sub.status, sub.razorpay_subscription_id, sub.stripe_customer_id) == ("razorpay", "active", "sub_R1", None)
    db.refresh(db.query(User).one())
    assert db.query(User).one().plan == "premium"  # standard plan entitles premium titles
    me = b.get("/billing/subscription").json()
    assert me["status"] == "active" and me["plan_code"] == "standard" and me["can_manage"] is False


def test_verify_rejects_someone_elses_subscription(make_user, db, rzp):
    victim, attacker = make_user("victim@example.com"), make_user("attacker@example.com")
    rzp["entity"] = entity(uid(db, "victim@example.com"))
    r = attacker.post("/billing/razorpay/verify", json=verify_body())  # even with a valid signature for that subscription id
    assert r.status_code == 403 and db.query(Subscription).count() == 0


def test_verify_survives_gateway_errors_without_granting_access(make_user, db, rzp):
    b = make_user()
    rzp["fail"] = True
    assert b.post("/billing/razorpay/verify", json=verify_body()).status_code == 502
    assert db.query(Subscription).count() == 0


def test_webhook_needs_a_valid_signature(make_user, db):
    b = make_user()
    assert hook(b, "subscription.activated", entity(uid(db)), secret="wrong").status_code == 400
    assert db.query(Subscription).count() == 0


def test_webhook_is_idempotent_and_tracks_the_lifecycle(make_user, db):
    b = make_user()
    u = uid(db)
    assert hook(b, "subscription.activated", entity(u), "evt_a", created=1000).status_code == 200
    assert hook(b, "subscription.activated", entity(u), "evt_a", created=1000).json().get("duplicate") is True
    assert db.query(Subscription).count() == 1 and db.query(StripeEvent).count() == 1
    assert hook(b, "subscription.pending", entity(u, "pending"), "evt_b", created=2000).status_code == 200
    assert db.query(Subscription).one().status == "past_due"
    assert db.query(User).one().plan == "premium"  # past_due keeps access while Razorpay retries
    hook(b, "subscription.activated", entity(u), "evt_c", created=1500)  # older than evt_b: ignored
    assert db.query(Subscription).one().status == "past_due"
    hook(b, "subscription.halted", entity(u, "halted"), "evt_d", created=3000)
    db.expire_all()
    assert db.query(Subscription).one().status == "expired" and db.query(User).one().plan == "free"
    assert b.get("/billing/subscription").json()["plan_code"] == "free"


def test_webhook_ignores_unrelated_events_and_unknown_plans(make_user, db):
    b = make_user()
    body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {}}}}).encode()
    r = b.c.post("/api/v1/billing/razorpay/webhook", content=body,
                 headers={"x-razorpay-signature": rz.sign_webhook(body, WH_SECRET)})
    assert r.status_code == 200 and r.json()["ignored"] is True
    odd = entity(uid(db))
    odd["plan_id"] = "plan_UNKNOWN"
    assert hook(b, "subscription.activated", odd, "evt_x").status_code == 200
    assert db.query(Subscription).count() == 0
    assert "no plan matches" in db.get(StripeEvent, "rzp:evt_x").error


def test_cancel_and_resume_autopay(make_user, db, rzp):
    b = make_user()
    rzp["entity"] = entity(uid(db))
    b.post("/billing/razorpay/verify", json=verify_body())
    assert b.post("/billing/cancel").status_code == 200
    assert any(p.endswith("/cancel") and body == {"cancel_at_cycle_end": 1} for _, p, body in rzp["calls"])
    assert b.get("/billing/subscription").json()["cancel_at_period_end"] is True
    assert b.post("/billing/resume").status_code == 200
    assert b.get("/billing/subscription").json()["cancel_at_period_end"] is False
    assert b.post("/billing/change-plan", json={"plan_code": "premium"}).status_code == 409
    assert b.post("/billing/portal").status_code == 409


def test_a_gateway_failure_on_cancel_changes_nothing(make_user, db, rzp):
    b = make_user()
    rzp["entity"] = entity(uid(db))
    b.post("/billing/razorpay/verify", json=verify_body())
    rzp["fail"] = True
    assert b.post("/billing/cancel").status_code == 502
    assert b.get("/billing/subscription").json()["cancel_at_period_end"] is False


def test_account_deletion_ends_the_razorpay_mandate_first(make_user, db, rzp):
    from conftest import PASSWORD
    b = make_user()
    rzp["entity"] = entity(uid(db))
    b.post("/billing/razorpay/verify", json=verify_body())
    rzp["fail"] = True
    assert b.post("/account/delete", json={"password": PASSWORD}).status_code == 502  # nothing deleted
    assert db.query(User).count() == 1
    rzp["fail"] = False
    assert b.post("/account/delete", json={"password": PASSWORD}).status_code == 200
    assert any(p.endswith("/cancel") and body == {"cancel_at_cycle_end": 0} for _, p, body in rzp["calls"])


def test_key_secret_never_appears_in_any_api_response(make_user, db, rzp):
    b = make_user()
    seen = [b.get("/billing/plans").text, b.post("/billing/razorpay/subscribe", json={"plan_code": "standard"}).text]
    assert all(KEY_SECRET not in t and WH_SECRET not in t for t in seen)


def test_signature_helpers():
    sig = rz.sign_checkout("pay_1", "sub_1", "k")
    assert sig == rz.sign_checkout("pay_1", "sub_1", "k") and sig != rz.sign_checkout("pay_2", "sub_1", "k")
    assert not rz.verify_webhook_signature(b"{}", None, "k") and not rz.verify_webhook_signature(b"{}", "x", "")


# ------------------------------------------------------------------ pay once: UPI / cards / net banking
def paid_order(user_id, plan="standard", amount=19900, status="paid", paid=None, **kw):
    return {"id": "order_O1", "status": status, "amount": amount, "amount_paid": amount if paid is None else paid,
            "currency": "INR", "notes": {"user_id": user_id, "plan_code": plan}, **kw}


def order_body(order="order_O1", pay="pay_9", secret=KEY_SECRET):
    return {"razorpay_order_id": order, "razorpay_payment_id": pay, "razorpay_signature": rz.sign_order(order, pay, secret)}


def test_order_uses_the_server_side_price_and_grants_nothing(make_user, db, rzp):
    b = make_user()
    r = b.post("/billing/razorpay/order", json={"plan_code": "standard"})
    assert r.status_code == 200 and r.json()["order_id"] == "order_O1" and r.json()["amount"] == 19900
    _, path, body = next(c for c in rzp["calls"] if c[1].endswith("/orders"))
    assert body["amount"] == 19900 and body["currency"] == "INR" and body["payment_capture"] == 1
    assert body["notes"]["user_id"] == uid(db)
    assert db.query(Subscription).count() == 0
    assert KEY_SECRET not in r.text


def test_verify_order_grants_thirty_days_and_is_idempotent(make_user, db, rzp):
    from datetime import datetime, timedelta, timezone
    b = make_user()
    rzp["order"] = paid_order(uid(db))
    assert b.post("/billing/razorpay/verify-order", json=order_body()).status_code == 200
    assert b.post("/billing/razorpay/verify-order", json=order_body()).status_code == 200  # replay: no second row
    sub = db.query(Subscription).one()
    assert (sub.provider, sub.status, sub.razorpay_payment_id, sub.razorpay_subscription_id) == ("razorpay", "active", "pay_9", None)
    end = sub.current_period_end if sub.current_period_end.tzinfo else sub.current_period_end.replace(tzinfo=timezone.utc)
    assert timedelta(days=29, hours=23) < end - datetime.now(timezone.utc) <= timedelta(days=30)
    assert db.query(User).one().plan == "premium"
    status = b.get("/billing/subscription").json()
    assert status["status"] == "active" and status["can_manage"] is False
    assert b.post("/billing/cancel").status_code == 409  # nothing renews
    assert "paid once" in b.post("/billing/cancel").json()["detail"]


@pytest.mark.parametrize("order,why", [
    (lambda u: paid_order(u, status="attempted", paid=0), "not paid"),
    (lambda u: paid_order(u, paid=100), "part paid"),
    (lambda u: paid_order(u, amount=100), "amount does not match our price"),
    (lambda u: paid_order(u, plan="nonexistent"), "unknown plan"),
])
def test_verify_order_refuses_incomplete_or_tampered_orders(make_user, db, rzp, order, why):
    b = make_user()
    rzp["order"] = order(uid(db))
    assert b.post("/billing/razorpay/verify-order", json=order_body()).status_code in (409, 400), why
    assert db.query(Subscription).count() == 0 and db.query(User).one().plan == "free"


def test_verify_order_rejects_forged_signature_and_foreign_orders(make_user, db, rzp):
    victim, attacker = make_user("victim@example.com"), make_user("attacker@example.com")
    rzp["order"] = paid_order(uid(db, "victim@example.com"))
    assert attacker.post("/billing/razorpay/verify-order", json=order_body(secret="wrong")).status_code == 400
    assert attacker.post("/billing/razorpay/verify-order", json=order_body()).status_code == 403
    assert db.query(Subscription).count() == 0


def test_one_time_plan_expires_and_access_ends(make_user, db, rzp):
    from datetime import datetime, timedelta, timezone
    from app.routers.billing import expire_prepaid
    b = make_user()
    rzp["order"] = paid_order(uid(db))
    b.post("/billing/razorpay/verify-order", json=order_body())
    assert expire_prepaid(db) == 0  # still inside the paid period
    sub = db.query(Subscription).one()
    sub.current_period_end = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert expire_prepaid(db) == 1
    db.expire_all()
    assert db.query(Subscription).one().status == "expired" and db.query(User).one().plan == "free"
    assert b.post("/billing/razorpay/order", json={"plan_code": "standard"}).status_code == 200  # can buy again


def test_a_lapsed_plan_is_noticed_when_the_user_next_checks_billing(make_user, db, rzp):
    from datetime import datetime, timedelta, timezone
    b = make_user()
    rzp["order"] = paid_order(uid(db))
    b.post("/billing/razorpay/verify-order", json=order_body())
    sub = db.query(Subscription).one()
    sub.current_period_end = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert b.get("/billing/subscription").json()["plan_code"] == "free"


def test_cannot_buy_twice_while_a_plan_is_live(make_user, db, rzp):
    b = make_user()
    rzp["order"] = paid_order(uid(db))
    b.post("/billing/razorpay/verify-order", json=order_body())
    assert b.post("/billing/razorpay/order", json={"plan_code": "standard"}).status_code == 409


def test_expiry_job_is_scheduled_in_the_worker():
    from app import worker
    assert "expire_prepaid" in worker.SCHEDULE and worker.SCHEDULE["expire_prepaid"][1] <= 600
