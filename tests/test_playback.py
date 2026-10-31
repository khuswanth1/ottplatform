from datetime import datetime, timezone

import pytest

from app.services.rights import evaluate_rights
from helpers import days, mk_asset, mk_episode, mk_right, mk_title

NOW = datetime.now(timezone.utc)


class R:  # light stand-in for TitleRight
    def __init__(self, **kw):
        self.status, self.starts_at, self.expires_at = "verified", None, None
        self.territories, self.entitlement = ["*"], "registered"
        self.__dict__.update(kw)


@pytest.mark.parametrize("rights,country,plan,code", [
    ([], "US", "free", "no_rights"),
    ([R(status="unverified")], "US", "free", "not_verified"),
    ([R(status="rejected")], "US", "free", "not_verified"),
    ([R(status="revoked")], "US", "free", "not_verified"),
    ([R(expires_at=days(-1))], "US", "free", "expired"),
    ([R(starts_at=days(1))], "US", "free", "not_started"),
    ([R(territories=["IN"])], "US", "free", "territory_blocked"),
    ([R(territories=["IN"])], None, "free", "territory_blocked"),
    ([R(entitlement="premium")], "US", "free", "entitlement_required"),
    ([R()], "US", "free", "ok"),
    ([R(territories=["us"])], "US", "free", "ok"),
    ([R(entitlement="premium")], "US", "premium", "ok"),
    ([R(status="unverified"), R()], "US", "free", "ok"),  # any valid right suffices
])
def test_rights_matrix(rights, country, plan, code):
    assert evaluate_rights(rights, NOW, country, plan).code == code


def test_no_rights_no_playback(make_user, db):
    t = mk_title(db)
    mk_asset(db, t)
    u = make_user()
    r = u.post("/playback/sessions", json={"title_id": str(t.id)})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "no_rights"
    assert r.json()["detail"]["alternatives"].endswith("/availability")


def test_unverified_rights_blocked(make_user, db):
    t = mk_title(db)
    mk_asset(db, t)
    mk_right(db, t, status="unverified")
    assert make_user().post("/playback/sessions", json={"title_id": str(t.id)}).status_code == 403


def test_verified_right_without_asset_is_404(make_user, db):
    t = mk_title(db)
    mk_right(db, t)
    r = make_user().post("/playback/sessions", json={"title_id": str(t.id)})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_authorized_source"


def test_authorized_playback(make_user, db):
    t = mk_title(db)
    mk_asset(db, t)
    mk_right(db, t)
    u = make_user()
    r = u.post("/playback/sessions", json={"title_id": str(t.id)})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "hls" and body["url"].endswith("index.m3u8") and body["title"]["direct"]["label"]
    assert u.delete(f"/playback/sessions/{body['session_id']}").status_code == 200


def test_requires_login(db):
    from conftest import Browser
    t = mk_title(db)
    assert Browser().post("/playback/sessions", json={"title_id": str(t.id)}).status_code == 401


def test_territory_enforced_by_trusted_country(make_user, db):
    t = mk_title(db)
    mk_asset(db, t)
    mk_right(db, t, territories=["IN"])
    u = make_user()
    u.country = "US"
    assert u.post("/playback/sessions", json={"title_id": str(t.id)}).json()["detail"]["code"] == "territory_blocked"
    u.country = "IN"
    assert u.post("/playback/sessions", json={"title_id": str(t.id)}).status_code == 201


def test_user_cannot_spoof_country_via_query(make_user, db):
    t = mk_title(db)
    mk_asset(db, t)
    mk_right(db, t, territories=["IN"])
    u = make_user()
    r = u.post("/playback/sessions?country=IN", json={"title_id": str(t.id)})
    assert r.status_code == 403


def test_expired_and_future_windows(make_user, db):
    u = make_user()
    for kw, code in (({"expires": days(-1)}, "expired"), ({"starts": days(2)}, "not_started")):
        t = mk_title(db, name=f"T {code}")
        mk_asset(db, t)
        mk_right(db, t, **kw)
        assert u.post("/playback/sessions", json={"title_id": str(t.id)}).json()["detail"]["code"] == code


def test_premium_entitlement(make_user, db):
    t = mk_title(db)
    mk_asset(db, t)
    mk_right(db, t, entitlement="premium")
    u = make_user()
    assert u.post("/playback/sessions", json={"title_id": str(t.id)}).json()["detail"]["code"] == "entitlement_required"
    from app.models import User
    usr = db.query(User).filter_by(email="user@example.com").one()
    usr.plan = "premium"
    db.commit()
    assert u.post("/playback/sessions", json={"title_id": str(t.id)}).status_code == 201


def test_kids_profile_blocked_from_adult_titles(make_user, db):
    adult, kid = mk_title(db, "Adult"), mk_title(db, "Kid", kids=True)
    for t in (adult, kid):
        mk_asset(db, t, url=f"https://cdn.example.com/{t.id}.m3u8")
        mk_right(db, t)
    u = make_user()
    u.profile = u.post("/profiles", json={"name": "Junior", "is_kids": True}).json()["id"]
    assert u.post("/playback/sessions", json={"title_id": str(adult.id)}).json()["detail"]["code"] == "kids_restricted"
    assert u.get(f"/titles/{adult.id}").status_code == 404
    assert u.post("/playback/sessions", json={"title_id": str(kid.id)}).status_code == 201


def test_draft_and_archived_titles_not_playable(make_user, db):
    u = make_user()
    for st in ("draft", "archived"):
        t = mk_title(db, f"T {st}", status=st)
        mk_asset(db, t)
        mk_right(db, t)
        assert u.post("/playback/sessions", json={"title_id": str(t.id)}).status_code == 404


def test_inactive_asset_ignored(make_user, db):
    t = mk_title(db)
    mk_asset(db, t, is_active=False)
    mk_right(db, t)
    assert make_user().post("/playback/sessions", json={"title_id": str(t.id)}).status_code == 404


def test_embed_host_allowlist(make_user, db):
    t = mk_title(db)
    mk_asset(db, t, kind="embed", url="https://evil.example/embed/x")
    mk_right(db, t)
    r = make_user().post("/playback/sessions", json={"title_id": str(t.id)})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "embed_host_not_allowed"


def test_allowed_embed(make_user, db):
    t = mk_title(db)
    mk_asset(db, t, kind="embed", url="https://archive.org/embed/old_film")
    mk_right(db, t)
    assert make_user().post("/playback/sessions", json={"title_id": str(t.id)}).json()["kind"] == "embed"


def test_signed_url(make_user, db, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "cdn_signing_secret", "s3cret")
    t = mk_title(db)
    mk_asset(db, t, requires_signing=True)
    mk_right(db, t)
    url = make_user().post("/playback/sessions", json={"title_id": str(t.id)}).json()["url"]
    assert "exp=" in url and "sig=" in url


def test_series_requires_episode_and_returns_neighbours(make_user, db):
    t = mk_title(db, "Show", type_="series")
    e1, e2, e3 = (mk_episode(db, t, n) for n in (1, 2, 3))
    for e in (e1, e2, e3):
        mk_asset(db, t, episode=e, url=f"https://cdn.example.com/{e.id}.m3u8")
    mk_right(db, t)
    u = make_user()
    first = u.post("/playback/sessions", json={"title_id": str(t.id)})  # Play on the series: starts at episode 1
    assert first.status_code == 201 and first.json()["episode_id"] == str(e1.id)
    u.delete(f"/playback/sessions/{first.json()['session_id']}")  # a free plan has one screen
    r = u.post("/playback/sessions", json={"title_id": str(t.id), "episode_id": str(e2.id)}).json()
    assert r["next_episode_id"] == str(e3.id) and r["previous_episode_id"] == str(e1.id)


def test_episode_of_other_title_rejected(make_user, db):
    t1, t2 = mk_title(db, "S1", type_="series"), mk_title(db, "S2", type_="series")
    e = mk_episode(db, t2)
    mk_asset(db, t1, episode=mk_episode(db, t1))
    mk_right(db, t1)
    assert make_user().post("/playback/sessions", json={"title_id": str(t1.id), "episode_id": str(e.id)}).status_code == 400


def test_resume_position_and_cross_account_session(make_user, db):
    t = mk_title(db)
    mk_asset(db, t)
    mk_right(db, t)
    a, b = make_user("a@example.com"), make_user("b@example.com")
    assert a.put("/watch-progress", json={"title_id": str(t.id), "position_seconds": 300, "duration_seconds": 6000}).status_code == 200
    s = a.post("/playback/sessions", json={"title_id": str(t.id)}).json()
    assert s["resume_position_seconds"] == 300
    assert b.delete(f"/playback/sessions/{s['session_id']}").status_code == 404  # not B's session


def test_availability_country_param_never_unlocks_direct_playback(make_user, db):
    """?country= only chooses which region's external providers are listed; direct access is judged on the
    trusted viewer country, so a right limited to another territory must not show as playable."""
    from app.config import get_settings
    viewer = get_settings().default_country.upper()
    other = "US" if viewer != "US" else "GB"
    t = mk_title(db)
    mk_asset(db, t)
    mk_right(db, t, territories=(other,))
    u = make_user()
    a = u.get(f"/titles/{t.id}/availability?country={other}").json()
    assert a["country"] == other and a["viewer_country"] == viewer
    assert a["direct"] is None
    assert u.post("/playback/sessions", json={"title_id": str(t.id)}).status_code == 403


# ---------------------------------------------------------------- the right video for the right title
def _open(db, name, url, type_="movie"):
    t = mk_title(db, name, type_=type_)
    mk_right(db, t)
    return t, mk_asset(db, t, url=url)


def test_each_title_gets_its_own_source_and_identity(make_user, db):
    a, _ = _open(db, "Film A", "https://cdn.example.com/a.m3u8")
    b, _ = _open(db, "Film B", "https://cdn.example.com/b.m3u8")
    u = make_user()
    ra = u.post("/playback/sessions", json={"title_id": str(a.id)}).json()
    u.delete(f"/playback/sessions/{ra['session_id']}")  # the free plan allows one screen; finish A before opening B
    rb = u.post("/playback/sessions", json={"title_id": str(b.id)}).json()
    assert (ra["url"], ra["title"]["id"], ra["title"]["name"]) == ("https://cdn.example.com/a.m3u8", str(a.id), "Film A")
    assert (rb["url"], rb["title"]["id"], rb["title"]["name"]) == ("https://cdn.example.com/b.m3u8", str(b.id), "Film B")
    assert "duration_seconds" not in ra  # real duration comes from the stream, never invented from TMDB runtime


def test_source_shared_by_two_titles_is_blocked_for_both(make_user, db):
    a, _ = _open(db, "Film A", "https://cdn.example.com/same.mp4")
    b, _ = _open(db, "Film B", "https://cdn.example.com/same.mp4")
    u = make_user()
    for t in (a, b):
        r = u.post("/playback/sessions", json={"title_id": str(t.id)})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "source_conflict"
        assert r.json()["detail"]["alternatives"].endswith("/availability")  # points at real providers instead


def test_same_source_on_two_episodes_is_blocked(make_user, db):
    s = mk_title(db, "Show", type_="series")
    mk_right(db, s)
    e1, e2 = mk_episode(db, s, 1), mk_episode(db, s, 2)
    mk_asset(db, s, url="https://cdn.example.com/ep.mp4", episode=e1)
    mk_asset(db, s, url="https://cdn.example.com/ep.mp4", episode=e2)
    r = make_user().post("/playback/sessions", json={"title_id": str(s.id), "episode_id": str(e1.id)})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "source_conflict"


def test_episode_session_echoes_requested_episode(make_user, db):
    s = mk_title(db, "Show", type_="series")
    mk_right(db, s)
    e1, e2 = mk_episode(db, s, 1), mk_episode(db, s, 2)
    mk_asset(db, s, url="https://cdn.example.com/e1.mp4", kind="mp4", episode=e1)
    mk_asset(db, s, url="https://cdn.example.com/e2.mp4", kind="mp4", episode=e2)
    u = make_user()
    r = u.post("/playback/sessions", json={"title_id": str(s.id), "episode_id": str(e2.id)}).json()
    assert r["episode_id"] == str(e2.id) and r["url"].endswith("/e2.mp4") and r["next_episode_id"] is None
    assert r["previous_episode_id"] == str(e1.id)


def test_admin_cannot_attach_one_url_to_two_titles(make_admin, db):
    admin = make_admin()
    a, b = mk_title(db, "A"), mk_title(db, "B")
    body = lambda t: {"title_id": str(t.id), "kind": "mp4", "url": "https://cdn.example.com/x.mp4"}
    assert admin.post("/admin/media-assets", json=body(a)).status_code == 201
    r = admin.post("/admin/media-assets", json=body(b))
    assert r.status_code == 409 and "only one" in r.json()["detail"]
