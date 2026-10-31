import uuid
from datetime import date, datetime, timedelta, timezone

from app.cache import cache
from app.models import Episode, MediaAsset, Notification, Profile, TitleRight, WatchlistItem
from app.services.notify import notify_all, notify_new_episodes, notify_now_playable
from helpers import mk_asset, mk_episode, mk_right, mk_title


def aired(db, ep, days_ago):
    ep.air_date = date.today() - timedelta(days=days_ago)
    db.commit()
    return ep


def prof(db, u):
    return db.get(Profile, uuid.UUID(u.profile))


def listed(db, u, title, days_ago=30):
    """Put a title on the profile's list, as if it had been added `days_ago` days back."""
    u.put(f"/watchlist/{title.id}")
    db.query(WatchlistItem).filter_by(profile_id=uuid.UUID(u.profile), title_id=title.id).update(
        {"added_at": datetime.now(timezone.utc) - timedelta(days=days_ago)})
    db.commit()


def kinds(u):
    cache.clear()  # the bell throttles its content scans; tests want a fresh look
    return [(n["kind"], n["title"]["name"], n["episode_label"]) for n in u.get("/notifications").json()["items"]]


def test_episode_of_a_listed_series_notifies_once_with_its_label(make_user, db):
    u, s = make_user(), mk_title(db, "Show", type_="series")
    listed(db, u, s)
    e = aired(db, mk_episode(db, s, 3), 2)
    e.name = "The Return"
    db.commit()
    assert kinds(u) == [("new_episode", "Show", "S1:E3 The Return")]
    assert kinds(u) == [("new_episode", "Show", "S1:E3 The Return")]          # asking again does not duplicate
    assert u.get("/notifications").json()["unread"] == 1


def test_a_whole_season_released_at_once_is_one_notification(make_user, db):
    u, s = make_user(), mk_title(db, "Binge", type_="series")
    listed(db, u, s)
    for n in range(1, 9):
        aired(db, mk_episode(db, s, n), 1)
    assert kinds(u) == [("new_episode", "Binge", "S1:E8 Ep 8")]


def test_a_later_episode_notifies_again_but_an_older_one_does_not(make_user, db):
    u, s = make_user(), mk_title(db, "Weekly", type_="series")
    listed(db, u, s)
    aired(db, mk_episode(db, s, 1), 9)
    assert len(kinds(u)) == 1
    aired(db, mk_episode(db, s, 2), 1)
    assert [k[2] for k in kinds(u)] == ["S1:E2 Ep 2", "S1:E1 Ep 1"]            # newest first
    aired(db, mk_episode(db, s, 0, season_no=0), 12)                            # an older special appears late: no news
    assert len(kinds(u)) == 2


def test_only_recent_aired_episodes_count(make_user, db):
    u, s = make_user(), mk_title(db, "Old", type_="series")
    listed(db, u, s)
    aired(db, mk_episode(db, s, 1), 30)                                          # too old
    future = mk_episode(db, s, 2)
    future.air_date = date.today() + timedelta(days=3)                           # not aired yet
    db.commit()
    assert kinds(u) == []


def test_title_added_after_the_episode_aired_is_not_news(make_user, db):
    u, s = make_user(), mk_title(db, "Late", type_="series")
    aired(db, mk_episode(db, s, 1), 6)
    u.put(f"/watchlist/{s.id}")                                                  # added today, episode aired 6 days ago
    assert kinds(u) == []


def test_watching_the_series_counts_as_interest_but_only_for_unseen_episodes(make_user, db):
    u, s = make_user(), mk_title(db, "Follow", type_="series")
    e1, e2 = aired(db, mk_episode(db, s, 1), 10), aired(db, mk_episode(db, s, 2), 2)
    u.put("/watch-progress", json={"title_id": str(s.id), "episode_id": str(e1.id), "position_seconds": 50, "duration_seconds": 3000})
    assert [k[2] for k in kinds(u)] == ["S1:E2 Ep 2"]
    u2, s2 = make_user("b@example.com"), mk_title(db, "Done", type_="series")
    e = aired(db, mk_episode(db, s2, 1), 2)
    u2.put("/watch-progress", json={"title_id": str(s2.id), "episode_id": str(e.id), "position_seconds": 50, "duration_seconds": 3000})
    assert kinds(u2) == []                                                       # the only new episode is the one they are on


def test_hidden_history_and_restricted_profiles_get_nothing(make_user, db):
    u, s = make_user(), mk_title(db, "Grown", type_="series")
    e1, _ = aired(db, mk_episode(db, s, 1), 10), aired(db, mk_episode(db, s, 2), 2)
    u.put("/watch-progress", json={"title_id": str(s.id), "episode_id": str(e1.id), "position_seconds": 50, "duration_seconds": 3000})
    u.delete(f"/watch-progress/{u.get('/watch-progress?history=true').json()[0]['id']}")
    assert kinds(u) == []                                                        # removed from activity: no longer a follower
    u.put(f"/watchlist/{s.id}")
    kid = u.post("/profiles", json={"name": "Kid", "maturity_level": "kids"}).json()["id"]
    p = db.get(Profile, uuid.UUID(kid))
    db.add(WatchlistItem(profile_id=p.id, title_id=s.id, kind="watchlist", added_at=datetime.now(timezone.utc) - timedelta(days=30)))
    db.commit()
    u.profile = kid
    assert kinds(u) == []                                                        # not family safe


def test_title_becomes_playable_after_it_was_listed(make_user, db):
    u, t = make_user(), mk_title(db, "Coming")
    u.put(f"/watchlist/{t.id}")
    assert kinds(u) == []
    mk_right(db, t)
    assert kinds(u) == []                                                        # a right alone is not enough
    mk_asset(db, t)
    assert kinds(u) == [("new_in_list", "Coming", None)]
    assert kinds(u) == [("new_in_list", "Coming", None)]


def test_already_playable_title_is_not_announced_and_expired_rights_do_not_count(make_user, db):
    u = make_user()
    t = mk_title(db, "Always")
    mk_right(db, t)
    mk_asset(db, t)
    u.put(f"/watchlist/{t.id}")                                                  # playable before it was listed
    expired = mk_title(db, "Lapsed")
    u.put(f"/watchlist/{expired.id}")
    mk_right(db, expired, expires=datetime.now(timezone.utc) - timedelta(days=1))
    mk_asset(db, expired)
    assert kinds(u) == []


def test_job_covers_everyone_and_the_bell_scan_is_throttled(make_user, db):
    a, b, s = make_user("a@example.com"), make_user("b@example.com"), mk_title(db, "Both", type_="series")
    for x in (a, b):
        listed(db, x, s)
    aired(db, mk_episode(db, s, 1), 1)
    out = notify_all(db)
    assert out == {"released": 0, "episodes": 2, "playable": 0}
    assert notify_all(db)["episodes"] == 0                                       # nothing twice
    assert a.get("/notifications").json()["unread"] == 1
    # throttle: a new episode right after the first bell scan waits for the next window or the job
    aired(db, mk_episode(db, s, 2), 0)
    assert a.get("/notifications").json()["unread"] == 1
    cache.clear()
    assert a.get("/notifications").json()["unread"] == 2
