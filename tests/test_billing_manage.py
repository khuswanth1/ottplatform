"""Change plan, cancel/resume and invoices against a fake Stripe. Nothing here talks to the real service."""
import httpx
import pytest

from app import stripe_client as stripe
from app.models import PlanPrice
from test_billing import event, price, stripe_env, sub_obj, uid_of  # noqa: F401  (stripe_env is an autouse fixture)


class FakeStripe:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.invoices = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = dict(httpx.QueryParams(req.content.decode())) if req.content else {}
        self.calls.append((req.method, req.url.path, body, dict(req.url.params)))
        if self.fail:
            return httpx.Response(402, json={"error": {"message": "Your card was declined."}})
        if req.method == "GET" and req.url.path.endswith("/subscriptions/sub_1"):
            return httpx.Response(200, json={"id": "sub_1", "items": {"data": [{"id": "si_1", "price": {"id": "price_standard"}}]}})
        if req.method == "GET" and req.url.path.endswith("/invoices"):
            return httpx.Response(200, json={"data": self.invoices})
        return httpx.Response(200, json={"id": "sub_1"})


@pytest.fixture
def fake(monkeypatch):
    f = FakeStripe()
    monkeypatch.setattr(stripe, "_transport", httpx.MockTransport(f))
    return f


def subscribe(u, db, plan="standard", email="user@example.com"):
    """A live subscription the way the webhook would create it."""
    price(db, "standard", 1000)
    price(db, "premium", 2000)
    price(db, "ads", 500)
    r = event(u, "evt_sub", "customer.subscription.created", sub_obj(uid_of(db, email), price_id=f"price_{plan}"))
    assert r.status_code == 200


def test_change_plan_calls_stripe_with_proration_and_waits_for_the_webhook(make_user, db, fake):
    u = make_user()
    subscribe(u, db)
    assert u.post("/billing/change-plan", json={"plan_code": "premium"}).status_code == 200
    method, path, body, _ = fake.calls[-1]
    assert (method, path.endswith("/subscriptions/sub_1")) == ("POST", True)
    assert body["items[0][id]"] == "si_1" and body["items[0][price]"] == "price_premium"
    assert body["proration_behavior"] == "create_prorations" and body["metadata[plan_code]"] == "premium"
    assert u.get("/billing/subscription").json()["plan_code"] == "standard"     # unchanged until Stripe says so
    event(u, "evt_up", "customer.subscription.updated", sub_obj(uid_of(db), price_id="price_premium"))
    assert u.get("/billing/subscription").json()["plan_code"] == "premium"


def test_change_plan_rejections(make_user, db, fake):
    u = make_user()
    assert u.post("/billing/change-plan", json={"plan_code": "premium"}).status_code == 409     # no plan yet
    subscribe(u, db)
    assert u.post("/billing/change-plan", json={"plan_code": "standard"}).status_code == 409     # same plan
    assert u.post("/billing/change-plan", json={"plan_code": "free"}).status_code == 422
    db.query(PlanPrice).filter_by(stripe_price_id="price_ads").delete()
    db.commit()
    assert u.post("/billing/change-plan", json={"plan_code": "ads"}).status_code == 400          # no price here
    assert not [c for c in fake.calls if c[0] == "POST"]                                          # Stripe never asked


def test_stripe_failure_changes_nothing_and_does_not_leak_details(make_user, db, fake):
    u = make_user()
    subscribe(u, db)
    fake.fail = True
    r = u.post("/billing/change-plan", json={"plan_code": "premium"})
    assert r.status_code == 502 and "declined" not in r.text and "Nothing was changed" in r.json()["detail"]
    assert u.get("/billing/subscription").json()["plan_code"] == "standard"


def test_cancel_and_resume_toggle_cancel_at_period_end(make_user, db, fake):
    u = make_user()
    subscribe(u, db)
    assert u.post("/billing/cancel").status_code == 200
    assert fake.calls[-1][2] == {"cancel_at_period_end": "true"}
    event(u, "evt_c", "customer.subscription.updated", sub_obj(uid_of(db), cancel_at_period_end=True))
    s = u.get("/billing/subscription").json()
    assert s["cancel_at_period_end"] is True and s["plan_code"] == "standard"      # still has the plan until the period ends
    assert u.post("/billing/resume").status_code == 200
    assert fake.calls[-1][2] == {"cancel_at_period_end": "false"}


def test_cancel_without_a_plan_is_refused(make_user, fake):
    u = make_user()
    assert u.post("/billing/cancel").status_code == 409 and u.post("/billing/resume").status_code == 409
    assert fake.calls == []


def test_invoices_are_mapped_and_unsafe_links_dropped(make_user, db, fake):
    u = make_user()
    subscribe(u, db)
    fake.invoices = [
        {"id": "in_1", "number": "A-0001", "created": 1900000000, "total": 1000, "currency": "usd", "status": "paid",
         "hosted_invoice_url": "https://invoice.stripe.com/i/abc"},
        {"id": "in_2", "created": 1890000000, "total": 500, "currency": "eur", "status": "open",
         "hosted_invoice_url": "javascript:alert(1)"},
    ]
    rows = u.get("/billing/invoices").json()
    assert [(r["id"], r["total_cents"], r["currency"], r["status"]) for r in rows] == [("in_1", 1000, "USD", "paid"), ("in_2", 500, "EUR", "open")]
    assert rows[0]["url"].startswith("https://") and rows[1]["url"] is None
    assert fake.calls[-1][3]["customer"] == "cus_1"


def test_invoices_empty_without_billing_account_and_502_on_failure(make_user, db, fake):
    u = make_user()
    assert u.get("/billing/invoices").json() == [] and fake.calls == []
    subscribe(u, db)
    fake.fail = True
    assert u.get("/billing/invoices").status_code == 502


def test_other_accounts_cannot_touch_my_subscription(make_user, db, fake):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    subscribe(a, db, email="a@example.com")
    assert b.post("/billing/cancel").status_code == 409 and b.post("/billing/change-plan", json={"plan_code": "premium"}).status_code == 409
    assert b.get("/billing/invoices").json() == []
    assert [c for c in fake.calls if c[0] == "POST" and "subscriptions" in c[1]] == []


def test_cancel_at_from_the_customer_portal_counts_as_ending(make_user, db, fake):
    u = make_user()
    subscribe(u, db)
    event(u, "evt_portal", "customer.subscription.updated", sub_obj(uid_of(db), cancel_at=1900000000))
    assert u.get("/billing/subscription").json()["cancel_at_period_end"] is True


class PriceStripe:
    """Answers GET /prices/{id} from a table, like the real API."""
    def __init__(self, table):
        self.table = table

    def __call__(self, req: httpx.Request) -> httpx.Response:
        pid = req.url.path.rsplit("/", 1)[-1]
        if pid not in self.table:
            return httpx.Response(404, json={"error": {"message": f"No such price: '{pid}'"}})
        return httpx.Response(200, json=self.table[pid])


def test_billing_check_flags_mismatches_and_passes_a_good_setup(make_user, db, monkeypatch, capsys):
    from app import cli
    s = stripe.get_settings()
    price(db, "standard", 1000)
    price(db, "premium", 2000)
    price(db, "ads", 500)
    good = {"active": True, "recurring": {"interval": "month"}, "unit_amount": 1000, "currency": "usd"}
    table = {"price_standard": good,
             "price_premium": {**good, "unit_amount": 2500},                      # amount differs
             "price_ads": {**good, "unit_amount": 500, "recurring": None}}        # one-off price
    monkeypatch.setattr(stripe, "_transport", httpx.MockTransport(PriceStripe(table)))
    assert cli.billing_check() == 2
    out = capsys.readouterr().out
    assert "ok      standard" in out and "2500 cents" in out and "not a monthly recurring" in out
    table["price_premium"], table["price_ads"] = {**good, "unit_amount": 2000}, {**good, "unit_amount": 500}
    assert cli.billing_check() == 0
    monkeypatch.setattr(s, "stripe_secret_key", "sk_live_x")
    assert cli.billing_check() == 1 and "LIVE" in capsys.readouterr().out          # refuses live keys unless told
    monkeypatch.setattr(s, "stripe_secret_key", "")
    assert cli.billing_check() == 1
