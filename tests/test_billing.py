import json
import time

import httpx
import pytest

from app import stripe_client as stripe
from app.config import get_settings
from app.models import Plan, PlanPrice, StripeEvent, Subscription, User
from helpers import mk_asset, mk_right, mk_title

SECRET = "whsec_test"


@pytest.fixture(autouse=True)
def stripe_env(monkeypatch, db):
    s = get_settings()
    monkeypatch.setattr(s, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(s, "stripe_webhook_secret", SECRET)
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.url.path, dict(httpx.QueryParams(req.content.decode()))))
        if req.url.path.endswith("/checkout/sessions"):
            return httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.example/pay"})
        return httpx.Response(200, json={"url": "https://portal.example/manage"})

    monkeypatch.setattr(stripe, "_transport", httpx.MockTransport(handler))
    # tests build tables from the models, so seed the plan rows the migration would insert
    db.add_all([Plan(code=c, name=n, has_ads=a, entitlement=e, sort=i) for i, (c, n, a, e) in enumerate([
        ("free", "Free", False, "registered"), ("ads", "With ads", True, "registered"),
        ("standard", "Standard", False, "premium"), ("premium", "Premium", False, "premium")])])
    db.commit()
    return calls


def price(db, code, cents=999, country="*", price_id=None):
    p = db.query(Plan).filter_by(code=code).one()
    db.add(PlanPrice(plan_id=p.id, country=country, currency="USD", amount_cents=cents,
                     stripe_price_id=price_id or f"price_{code}"))
    db.commit()


def event(b, eid, etype, obj, created=None, secret=SECRET, sig_time=None):
    body = json.dumps({"id": eid, "type": etype, "created": created or int(time.time()), "data": {"object": obj}}).encode()
    return b.c.post("/api/v1/billing/webhook", content=body, headers={"stripe-signature": stripe.sign(body, secret, sig_time)})


def sub_obj(uid, sid="sub_1", status="active", price_id="price_standard", customer="cus_1", **kw):
    base = {"id": sid, "customer": customer, "status": status, "metadata": {"user_id": str(uid), "plan_code": "standard"},
            "cancel_at_period_end": False, "items": {"data": [{"price": {"id": price_id}, "current_period_end": 1900000000}]}}
    return {**base, **kw}


def uid_of(db, email="user@example.com"):
    return db.query(User).filter_by(email=email).one().id


def test_plans_list_prices_by_country_and_purchasable(make_user, db):
    price(db, "standard", 1299, "*")
    price(db, "standard", 399, "IN", "price_standard_in")
    b = make_user()
    data = b.get("/billing/plans").json()
    assert data["enabled"] is True
    by = {p["code"]: p for p in data["plans"]}
    assert by["standard"]["price"] == {"currency": "USD", "amount_cents": 1299} and by["standard"]["purchasable"]
    assert by["premium"]["price"] is None and not by["premium"]["purchasable"]
    assert by["free"]["purchasable"] is False and by["standard"]["premium_titles"] is True
    b.country = "IN"
    assert {p["code"]: p for p in b.get("/billing/plans").json()["plans"]}["standard"]["price"]["amount_cents"] == 399


def test_checkout_creates_session_with_user_metadata(make_user, db, stripe_env):
    price(db, "standard")
    b = make_user()
    r = b.post("/billing/checkout", json={"plan_code": "standard"})
    assert r.status_code == 200 and r.json()["url"] == "https://checkout.example/pay"
    path, form = stripe_env[-1]
    assert form["client_reference_id"] == str(uid_of(db)) and form["line_items[0][price]"] == "price_standard"
    assert form["customer_email"] == "user@example.com" and form["mode"] == "subscription"
    assert form["success_url"].endswith("/account?checkout=success")


def test_checkout_rejections(make_user, db, monkeypatch):
    b = make_user()
    assert b.post("/billing/checkout", json={"plan_code": "standard"}).status_code == 400  # unpriced
    assert b.post("/billing/checkout", json={"plan_code": "free"}).status_code == 422
    price(db, "standard")
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "")
    assert b.post("/billing/checkout", json={"plan_code": "standard"}).status_code == 503


def test_unverified_user_cannot_check_out(make_user, db):
    price(db, "standard")
    assert make_user("anon@example.com", verify=False).post("/billing/checkout", json={"plan_code": "standard"}).status_code in (401, 403)


def test_webhook_rejects_bad_signatures(make_user, db):
    b = make_user()
    obj = sub_obj(uid_of(db))
    assert event(b, "evt_a", "customer.subscription.created", obj, secret="whsec_wrong").status_code == 400
    assert event(b, "evt_b", "customer.subscription.created", obj, sig_time=int(time.time()) - 3600).status_code == 400
    assert b.c.post("/api/v1/billing/webhook", content=b"{}").status_code == 400
    assert db.query(StripeEvent).count() == 0 and db.query(Subscription).count() == 0


def test_subscription_lifecycle_updates_plan_and_playback(make_user, db):
    price(db, "standard")
    b = make_user()
    uid = uid_of(db)
    t = mk_title(db, "Premium Film")
    mk_asset(db, t)
    mk_right(db, t, entitlement="premium")
    assert b.post("/playback/sessions", json={"title_id": str(t.id)}).status_code == 403
    assert event(b, "evt_1", "customer.subscription.created", sub_obj(uid)).status_code == 200
    db.expire_all()
    assert db.get(User, uid).plan == "premium"
    assert b.get("/billing/subscription").json()["plan_code"] == "standard"
    assert b.post("/playback/sessions", json={"title_id": str(t.id)}).status_code == 201
    event(b, "evt_2", "customer.subscription.updated", sub_obj(uid, cancel_at_period_end=True))
    assert b.get("/billing/subscription").json()["cancel_at_period_end"] is True
    event(b, "evt_3", "customer.subscription.deleted", sub_obj(uid, status="canceled"))
    db.expire_all()
    assert db.get(User, uid).plan == "free"
    sub = b.get("/billing/subscription").json()
    assert sub["plan_code"] == "free" and sub["status"] == "cancelled"


def test_webhook_replay_is_idempotent(make_user, db):
    price(db, "standard")
    b = make_user()
    obj = sub_obj(uid_of(db))
    assert event(b, "evt_dup", "customer.subscription.created", obj).json().get("duplicate") is None
    assert event(b, "evt_dup", "customer.subscription.created", obj).json()["duplicate"] is True
    assert db.query(Subscription).count() == 1 and db.query(StripeEvent).count() == 1


def test_out_of_order_events_do_not_regress_state(make_user, db):
    price(db, "standard")
    b = make_user()
    uid = uid_of(db)
    now = int(time.time())
    event(b, "evt_new", "customer.subscription.updated", sub_obj(uid, status="canceled"), created=now)
    event(b, "evt_old", "customer.subscription.created", sub_obj(uid, status="active"), created=now - 100)  # arrives late
    assert db.query(Subscription).one().status == "cancelled"
    db.expire_all()
    assert db.get(User, uid).plan == "free"


def test_past_due_keeps_access_and_unknown_plan_is_recorded(make_user, db):
    price(db, "standard")
    b = make_user()
    uid = uid_of(db)
    event(b, "evt_pd", "customer.subscription.created", sub_obj(uid, status="past_due"))
    db.expire_all()
    assert db.get(User, uid).plan == "premium" and b.get("/billing/subscription").json()["status"] == "past_due"
    bad = sub_obj(uid, sid="sub_x", price_id="price_unknown", metadata={"user_id": str(uid)})
    assert event(b, "evt_bad", "customer.subscription.updated", bad).status_code == 200
    db.expire_all()
    assert "no plan" in db.get(StripeEvent, "evt_bad").error


def test_second_live_subscription_is_recorded_not_retried(make_user, db):
    price(db, "standard")
    b = make_user()
    uid = uid_of(db)
    event(b, "evt_a", "customer.subscription.created", sub_obj(uid))
    assert event(b, "evt_b", "customer.subscription.created", sub_obj(uid, sid="sub_2")).status_code == 200
    db.expire_all()
    assert "integrity" in db.get(StripeEvent, "evt_b").error
    assert db.query(Subscription).count() == 1


def test_checkout_completed_links_customer_and_portal_works(make_user, db, stripe_env):
    price(db, "premium")
    b = make_user()
    uid = uid_of(db)
    obj = {"mode": "subscription", "subscription": "sub_9", "customer": "cus_9", "client_reference_id": str(uid),
           "payment_status": "paid", "metadata": {"plan_code": "premium"}}
    event(b, "evt_co", "checkout.session.completed", obj)
    db.expire_all()
    assert db.get(User, uid).plan == "premium"
    r = b.post("/billing/portal")
    assert r.status_code == 200 and stripe_env[-1][1]["customer"] == "cus_9"
    assert b.post("/billing/checkout", json={"plan_code": "premium"}).status_code == 409  # already subscribed


def test_portal_without_billing_account(make_user):
    assert make_user().post("/billing/portal").status_code == 409


def test_subscriptions_are_private_between_accounts(make_user, db):
    price(db, "standard")
    a, c = make_user("a@example.com"), make_user("c@example.com")
    event(a, "evt_p", "customer.subscription.created", sub_obj(uid_of(db, "a@example.com")))
    assert c.get("/billing/subscription").json()["status"] == "none"
