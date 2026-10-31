import httpx
import pytest

from app import stripe_client as stripe
from app.config import get_settings
from app.models import (
    AuditLog, AuthSession, Plan, Profile, Subscription, TitleRating, User, WatchlistItem, WatchProgress,
)
from conftest import PASSWORD, Browser
from helpers import mk_title

DELETE = "/account/delete"


def counts(db, user_id):
    return {m.__name__: db.query(m).filter(getattr(m, "user_id") == user_id).count() for m in (Profile, AuthSession, Subscription)}


def test_wrong_password_deletes_nothing(make_user, db):
    u = make_user()
    assert u.post(DELETE, json={"password": "wrong password"}).status_code == 403
    assert u.get("/auth/me").status_code == 200 and db.query(User).count() == 1


def test_deletes_the_account_and_everything_under_it_but_not_other_people(make_user, db):
    a, b, t = make_user("a@example.com"), make_user("b@example.com"), mk_title(db)
    a.put(f"/watchlist/{t.id}")
    a.put(f"/titles/{t.id}/rating", json={"value": 1})
    a.put("/watch-progress", json={"title_id": str(t.id), "position_seconds": 10, "duration_seconds": 100})
    b.put(f"/watchlist/{t.id}")
    uid = db.query(User).filter_by(email="a@example.com").one().id
    r = a.post(DELETE, json={"password": PASSWORD})
    assert r.status_code == 200
    db.expire_all()
    assert db.query(User).filter_by(email="a@example.com").count() == 0
    assert all(v == 0 for v in counts(db, uid).values())
    assert db.query(Profile).count() == 1 and db.query(WatchlistItem).count() == 1      # only B's remain
    assert db.query(TitleRating).count() == 0 and db.query(WatchProgress).count() == 0
    assert a.get("/auth/me").status_code == 401                                          # signed out everywhere
    assert Browser().post("/auth/login", json={"email": "a@example.com", "password": PASSWORD}).status_code == 401
    assert b.get("/auth/me").status_code == 200
    log = db.query(AuditLog).filter_by(action="account.deleted").one()
    assert log.actor_user_id is None                                                      # no link back to the person


def test_every_sign_in_of_the_account_dies_with_it(make_user, db):
    a = make_user()
    other = Browser()
    other.csrf = other.post("/auth/login", json={"email": "user@example.com", "password": PASSWORD}).json()["csrf_token"]
    assert a.post(DELETE, json={"password": PASSWORD}).status_code == 200
    assert other.get("/auth/me").status_code == 401


def test_last_admin_cannot_delete_themselves(make_admin, db):
    admin = make_admin()
    r = admin.post(DELETE, json={"password": PASSWORD})
    assert r.status_code == 409 and db.query(User).count() == 1


def test_requires_login():
    assert Browser().post(DELETE, json={"password": "x"}).status_code == 401


@pytest.fixture
def paid(db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "stripe_secret_key", "sk_test_x")
    db.add(Plan(code="standard", name="Standard", entitlement="premium", sort=2))
    db.commit()
    calls = []

    class Fake:
        fail = False

        def __call__(self, req: httpx.Request) -> httpx.Response:
            calls.append((req.method, req.url.path))
            if self.fail:
                return httpx.Response(500, json={"error": {"message": "boom"}})
            return httpx.Response(200, json={"id": "sub_1", "status": "canceled"})

    fake = Fake()
    monkeypatch.setattr(stripe, "_transport", httpx.MockTransport(fake))
    return fake, calls


def subscribe(db, email="user@example.com"):
    user = db.query(User).filter_by(email=email).one()
    plan = db.query(Plan).filter_by(code="standard").one()
    db.add(Subscription(user_id=user.id, plan_id=plan.id, status="active", stripe_customer_id="cus_1", stripe_subscription_id="sub_1"))
    db.commit()


def test_paid_plan_is_ended_at_stripe_before_deleting(make_user, db, paid):
    fake, calls = paid
    u = make_user()
    subscribe(db)
    assert u.post(DELETE, json={"password": PASSWORD}).status_code == 200
    assert calls == [("DELETE", "/v1/subscriptions/sub_1")]
    db.expire_all()
    assert db.query(User).count() == 0 and db.query(Subscription).count() == 0


def test_if_stripe_cannot_cancel_nothing_is_deleted(make_user, db, paid):
    fake, calls = paid
    fake.fail = True
    u = make_user()
    subscribe(db)
    r = u.post(DELETE, json={"password": PASSWORD})
    assert r.status_code == 502 and "nothing was deleted" in r.json()["detail"] and "boom" not in r.text
    db.expire_all()
    assert db.query(User).count() == 1 and db.query(Subscription).count() == 1
    assert u.get("/auth/me").status_code == 200
