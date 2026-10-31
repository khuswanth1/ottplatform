from datetime import date, timedelta

from conftest import Browser
from helpers import mk_title


def upcoming(db, name="Soon", days=10, **kw):
    t = mk_title(db, name, **kw)
    t.release_date = date.today() + timedelta(days=days)
    db.commit()
    return t


def release(db, title, days_ago=0):
    title.release_date = date.today() - timedelta(days=days_ago)
    db.commit()


def test_remind_is_idempotent_and_listed_until_released(make_user, db):
    u, t = make_user(), upcoming(db)
    assert u.put(f"/reminders/{t.id}").status_code == 204 and u.put(f"/reminders/{t.id}").status_code == 204
    assert u.get("/reminders/ids").json() == [str(t.id)]
    assert u.delete(f"/reminders/{t.id}").status_code == 204 and u.delete(f"/reminders/{t.id}").status_code == 204
    assert u.get("/reminders/ids").json() == []


def test_cannot_remind_for_released_undated_or_hidden_titles(make_user, db):
    u = make_user()
    assert u.put(f"/reminders/{mk_title(db, 'Out').id}").status_code == 409                 # no release date
    out = upcoming(db, "AlreadyOut", days=-3)
    assert u.put(f"/reminders/{out.id}").status_code == 409                                    # released
    assert u.put(f"/reminders/{upcoming(db, 'Draft', status='draft').id}").status_code == 404
    assert u.put("/reminders/00000000-0000-0000-0000-000000000000").status_code == 404
    kid_blocked = upcoming(db, "Grown")
    u.profile = u.post("/profiles", json={"name": "Kid", "maturity_level": "kids"}).json()["id"]
    assert u.put(f"/reminders/{kid_blocked.id}").status_code == 404                            # not family-safe


def test_release_creates_one_notification_and_ends_the_reminder(make_user, db):
    u, t = make_user(), upcoming(db)
    u.put(f"/reminders/{t.id}")
    assert u.get("/notifications").json() == {"items": [], "unread": 0}   # not out yet
    release(db, t)
    r = u.get("/notifications").json()
    assert r["unread"] == 1 and r["items"][0]["title"]["name"] == "Soon" and r["items"][0]["kind"] == "reminder_released"
    assert len(u.get("/notifications").json()["items"]) == 1               # opening it again does not duplicate
    assert u.get("/reminders/ids").json() == []                            # the reminder is spent


def test_mark_read_one_and_all(make_user, db):
    u = make_user()
    ts = [upcoming(db, f"T{i}") for i in range(3)]
    for t in ts:
        u.put(f"/reminders/{t.id}")
        release(db, t)
    items = u.get("/notifications").json()["items"]
    assert u.post("/notifications/read", json={"ids": [items[0]["id"]]}).status_code == 200
    assert u.get("/notifications").json()["unread"] == 2
    u.post("/notifications/read", json={"all": True})
    assert u.get("/notifications").json()["unread"] == 0


def test_notifications_belong_to_the_profile(make_user, db):
    a, b, t = make_user("a@example.com"), make_user("b@example.com"), upcoming(db)
    a.put(f"/reminders/{t.id}")
    release(db, t)
    n = a.get("/notifications").json()["items"][0]
    assert b.get("/notifications").json() == {"items": [], "unread": 0}
    b.post("/notifications/read", json={"ids": [n["id"]]})                  # someone else's id does nothing
    assert a.get("/notifications").json()["unread"] == 1


def test_job_makes_notifications_for_everyone_and_needs_login_for_api(make_user, db):
    from app.jobs import release_notify
    u, v, t = make_user("a@example.com"), make_user("b@example.com"), upcoming(db)
    for x in (u, v):
        x.put(f"/reminders/{t.id}")
    release(db, t)
    assert release_notify() == 2 and release_notify() == 0
    assert u.get("/notifications").json()["unread"] == 1
    assert Browser().get("/notifications").status_code == 401


def test_cards_carry_the_release_date(make_user, db):
    u, t = make_user(), upcoming(db, days=5)
    r = u.get("/watchlist/ids")  # sanity: route works
    u.put(f"/watchlist/{t.id}")
    assert u.get("/watchlist").json()["items"][0]["release_date"] == str(t.release_date)
