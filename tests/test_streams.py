import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import PlaybackSession, Plan, Subscription, User
from conftest import PASSWORD, Browser
from helpers import mk_asset, mk_right, mk_title


@pytest.fixture(autouse=True)
def plans(db):
    """Tests build tables from the models, so the rows migration 0004 seeds are added here (same limits)."""
    for i, (code, streams, ent) in enumerate([("free", 1, "registered"), ("ads", 1, "registered"), ("standard", 2, "premium"), ("premium", 4, "premium")]):
        db.add(Plan(code=code, name=code.title(), max_streams=streams, entitlement=ent, has_ads=code == "ads", sort=i))
    db.commit()


def film(db, name, url=None):
    t = mk_title(db, name)
    mk_right(db, t)
    mk_asset(db, t, url=url or f"https://cdn.example.com/{name.replace(' ', '-')}.m3u8")
    return t


def start(u, t):
    return u.post("/playback/sessions", json={"title_id": str(t.id)})


def second_device(email="user@example.com"):
    b = Browser()
    r = b.post("/auth/login", json={"email": email, "password": PASSWORD})
    b.csrf = r.json()["csrf_token"]
    return b


def subscribe(db, email, plan_code):
    user = db.query(User).filter_by(email=email).one()
    plan = db.query(Plan).filter_by(code=plan_code).one()
    db.add(Subscription(user_id=user.id, plan_id=plan.id, status="active", stripe_customer_id="cus_test"))
    db.commit()


def age(db, session_id, seconds):
    ps = db.get(PlaybackSession, uuid.UUID(session_id))
    ps.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    db.commit()


def test_free_plan_allows_one_screen_and_says_why(make_user, db):
    u, a, b = make_user(), film(db, "A"), film(db, "B")
    assert start(u, a).status_code == 201
    r = start(u, b)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stream_limit"
    assert "1 screen" in r.json()["detail"]["message"]


def test_ending_a_stream_frees_the_slot(make_user, db):
    u, a, b = make_user(), film(db, "A"), film(db, "B")
    sid = start(u, a).json()["session_id"]
    assert start(u, b).status_code == 409
    u.delete(f"/playback/sessions/{sid}")
    assert start(u, b).status_code == 201


def test_a_silent_player_loses_its_slot_after_the_lease_runs_out(make_user, db):
    u, a, b = make_user(), film(db, "A"), film(db, "B")
    sid = start(u, a).json()["session_id"]
    age(db, sid, 60)
    assert start(u, b).status_code == 409           # still inside the 90 s lease
    age(db, sid, 120)
    assert start(u, b).status_code == 201           # lapsed: the tab was closed without telling us


def test_heartbeat_keeps_the_slot_alive(make_user, db):
    u, a, b = make_user(), film(db, "A"), film(db, "B")
    sid = start(u, a).json()["session_id"]
    age(db, sid, 80)
    assert u.post(f"/playback/sessions/{sid}/heartbeat").status_code == 200
    assert start(u, b).status_code == 409           # refreshed, so B is still refused


def test_late_heartbeat_is_refused_when_the_slot_was_taken(make_user, db):
    u, a, b = make_user(), film(db, "A"), film(db, "B")
    sid = start(u, a).json()["session_id"]
    age(db, sid, 120)
    other = second_device()
    other.profile = u.profile
    assert start(other, b).status_code == 201       # the other device took the lapsed slot
    r = u.post(f"/playback/sessions/{sid}/heartbeat")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stream_limit"
    assert u.post(f"/playback/sessions/{sid}/heartbeat").status_code == 410   # and that stream is over


def test_late_heartbeat_resumes_when_nothing_took_the_slot(make_user, db):
    u, a = make_user(), film(db, "A")
    sid = start(u, a).json()["session_id"]
    age(db, sid, 120)
    assert u.post(f"/playback/sessions/{sid}/heartbeat").status_code == 200


def test_same_profile_reopening_the_same_title_replaces_its_own_stream(make_user, db):
    u, a = make_user(), film(db, "A")
    assert start(u, a).status_code == 201
    assert start(u, a).status_code == 201           # a page reload does not lock the viewer out


def test_limit_covers_every_profile_of_the_account(make_user, db):
    u, a, b = make_user(), film(db, "A"), film(db, "B")
    start(u, a)
    u.profile = u.post("/profiles", json={"name": "Second"}).json()["id"]
    assert start(u, b).status_code == 409


def test_paid_plan_raises_the_limit(make_user, db):
    u, a, b, c = make_user(), film(db, "A"), film(db, "B"), film(db, "C")
    subscribe(db, "user@example.com", "standard")   # 2 screens
    assert start(u, a).status_code == 201 and start(u, b).status_code == 201
    assert start(u, c).status_code == 409 and "2 screens" in start(u, c).json()["detail"]["message"]


def test_other_accounts_are_not_counted(make_user, db):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    t = film(db, "A")
    assert start(a, t).status_code == 201 and start(b, t).status_code == 201


def test_admin_is_not_limited(make_admin, db):
    admin, a, b = make_admin(), film(db, "A"), film(db, "B")
    assert start(admin, a).status_code == 201 and start(admin, b).status_code == 201


def test_heartbeat_belongs_to_the_session_owner(make_user, db):
    a, b, t = make_user("a@example.com"), make_user("b@example.com"), film(db, "A")
    sid = start(a, t).json()["session_id"]
    assert b.post(f"/playback/sessions/{sid}/heartbeat").status_code == 404
    a.delete(f"/playback/sessions/{sid}")
    assert a.post(f"/playback/sessions/{sid}/heartbeat").status_code == 410


def test_plans_list_shows_screens(make_user):
    u = make_user()
    plans = {p["code"]: p["max_streams"] for p in u.get("/billing/plans").json()["plans"]}
    assert plans == {"free": 1, "ads": 1, "standard": 2, "premium": 4}


def test_two_devices_starting_at_once_cannot_both_take_the_only_slot(make_user, db):
    """Only meaningful on PostgreSQL (the advisory lock); SQLite serialises writers by itself."""
    import threading
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("needs PostgreSQL")
    u = make_user()
    films = [film(db, f"Race{i}") for i in range(8)]
    devices = [u] + [second_device() for _ in range(3)]
    for d in devices:
        d.profile = u.profile
    for rnd in range(4):
        for ps in db.query(PlaybackSession).all():
            ps.ended_at = datetime.now(timezone.utc)  # free every slot between rounds
        db.commit()
        gate, results = threading.Barrier(len(devices)), []

        def go(dev, t):
            gate.wait()
            results.append(start(dev, t).status_code)

        threads = [threading.Thread(target=go, args=(d, films[(rnd * 2 + i) % len(films)])) for i, d in enumerate(devices)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert sorted(results) == [201, 409, 409, 409], results
