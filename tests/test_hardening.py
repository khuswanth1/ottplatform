"""Regression tests for the security/reliability audit fixes (see docs/AUDIT.md)."""
import re
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from app import worker
from app.cache import cache
from app.config import Settings, get_settings, production_problems
from app.models import PlaybackSession
from app.security import sign_media_url, validate_password_strength, verify_media_signature
from helpers import mk_asset, mk_right, mk_title


# ------------------------------------------------------------------ download endpoint
def test_download_requires_sign_in(db):
    from fastapi.testclient import TestClient
    from app.main import app
    t = mk_title(db)
    mk_asset(db, t, kind="mp4", url="https://cdn.example.com/f.mp4")
    mk_right(db, t)
    r = TestClient(app).get(f"/api/v1/playback/{t.id}/download", follow_redirects=False)
    assert r.status_code == 401  # used to redirect to the raw media URL for anyone


def test_download_needs_rights_and_never_falls_back_to_a_sample_video(make_user, db):
    t = mk_title(db)
    mk_asset(db, t, kind="mp4", url="https://cdn.example.com/f.mp4")
    u = make_user()
    r = u.get(f"/playback/{t.id}/download", follow_redirects=False)  # no verified right on file
    assert r.status_code == 403 and r.json()["detail"]["code"] == "no_rights"
    assert "location" not in r.headers
    missing = u.get("/playback/00000000-0000-0000-0000-000000000000/download", follow_redirects=False)
    assert missing.status_code == 404


def test_download_only_for_mp4_with_rights(make_user, db):
    mp4, hls = mk_title(db, "Clip"), mk_title(db, "Stream")
    mk_asset(db, mp4, kind="mp4", url="https://cdn.example.com/clip.mp4")
    mk_asset(db, hls, kind="hls", url="https://cdn.example.com/stream/index.m3u8")
    for t in (mp4, hls):
        mk_right(db, t)
    u = make_user()
    ok = u.get(f"/playback/{mp4.id}/download", follow_redirects=False)
    assert ok.status_code == 307 and ok.headers["location"] == "https://cdn.example.com/clip.mp4"
    assert ok.headers["cache-control"] == "no-store"
    no = u.get(f"/playback/{hls.id}/download", follow_redirects=False)
    assert no.status_code == 404 and no.json()["detail"]["code"] == "not_downloadable"


def test_download_respects_profile_maturity(make_user, db):
    t = mk_title(db, "Gritty")
    t.age_rating = "R"
    db.commit()
    mk_asset(db, t, kind="mp4", url="https://cdn.example.com/g.mp4")
    mk_right(db, t)
    u = make_user()
    teen = u.post("/profiles", json={"name": "Teen", "maturity_level": "7+"}).json()["id"]
    r = u.get(f"/playback/{t.id}/download", params={"profile_id": teen}, follow_redirects=False)
    assert r.status_code == 404
    other = make_user("other@example.com")  # someone else's profile id must not be usable
    r2 = other.get(f"/playback/{t.id}/download", params={"profile_id": teen}, follow_redirects=False)
    assert r2.status_code == 404


# ------------------------------------------------------------------ signed media + delivery-layer authorization
def _signed_session(make_user, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "cdn_signing_secret", "s3cret")
    t = mk_title(db)
    mk_asset(db, t, requires_signing=True, url="https://cdn.example.com/a/index.m3u8")
    mk_right(db, t)
    u = make_user()
    body = u.post("/playback/sessions", json={"title_id": str(t.id)}).json()
    q = {k: v[0] for k, v in parse_qs(urlsplit(body["url"]).query).items()}
    return u, body, q, urlsplit(body["url"]).path


def test_signed_url_is_bound_to_its_playback_session(make_user, db, monkeypatch):
    u, body, q, path = _signed_session(make_user, db, monkeypatch)
    assert q["sid"] == body["session_id"]
    auth = lambda **o: u.c.get("/api/v1/playback/authorize", params={"path": path, **q, **o})  # noqa: E731
    assert auth().status_code == 204
    assert auth(path="/other/file.ts").status_code == 403  # token minted for another path
    assert auth(sig="0" * 64).status_code == 403
    assert auth(exp=int(q["exp"]) + 1).status_code == 403  # expiry is part of the signature
    assert auth(sid="not-a-uuid").status_code == 403


def test_authorization_stops_when_the_playback_session_ends(make_user, db, monkeypatch):
    u, body, q, path = _signed_session(make_user, db, monkeypatch)
    params = {"path": path, **q}
    assert u.c.get("/api/v1/playback/authorize", params=params).status_code == 204
    assert u.delete(f"/playback/sessions/{body['session_id']}").status_code == 200
    assert u.c.get("/api/v1/playback/authorize", params=params).status_code == 403


def test_signature_expiry_and_missing_secret():
    url = sign_media_url("https://cdn.example.com/x.m3u8?a=1", "k", 60, "sid-1")
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert q["a"] == "1"
    assert verify_media_signature("k", "/x.m3u8", int(q["exp"]), "sid-1", q["sig"])
    assert not verify_media_signature("k", "/x.m3u8", int(q["exp"]), "sid-1", q["sig"], now=time.time() + 120)
    assert not verify_media_signature("other", "/x.m3u8", int(q["exp"]), "sid-1", q["sig"])
    assert not verify_media_signature("", "/x.m3u8", int(q["exp"]), "sid-1", q["sig"])
    with pytest.raises(ValueError):
        sign_media_url("https://cdn.example.com/x.m3u8", "", 60)


def test_asset_requiring_signing_fails_closed_without_a_secret(make_user, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "cdn_signing_secret", "")
    t = mk_title(db)
    mk_asset(db, t, requires_signing=True)
    mk_right(db, t)
    u = make_user()
    r = u.post("/playback/sessions", json={"title_id": str(t.id)})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "signing_unavailable"
    assert db.query(PlaybackSession).count() == 0  # the failed attempt did not take a screen


# ------------------------------------------------------------------ maturity in search
def test_search_honours_profile_maturity_level(make_user, db, upstream):
    r_rated = mk_title(db, "Alpha Gritty")
    r_rated.age_rating = "R"
    pg = mk_title(db, "Alpha Gentle")
    pg.age_rating = "PG"
    db.commit()
    u = make_user()
    adult = {i["name"] for i in u.get("/catalog/search", params={"q": "Alpha"}).json()["items"]}
    assert {"Alpha Gritty", "Alpha Gentle"} <= adult
    teen = u.post("/profiles", json={"name": "Teen", "maturity_level": "7+"}).json()["id"]
    u.profile = teen
    names = {i["name"] for i in u.get("/catalog/search", params={"q": "Alpha"}).json()["items"]}
    assert "Alpha Gentle" in names and "Alpha Gritty" not in names


# ------------------------------------------------------------------ response headers
def test_personalised_responses_are_never_publicly_cacheable(make_user, upstream):
    from fastapi.testclient import TestClient
    from app.main import app
    u = make_user()
    anon = TestClient(app).get("/api/v1/catalog/genres")  # no cookie, no profile header
    assert anon.headers["cache-control"].startswith("public")
    mine = u.get("/catalog/home")  # carries the session cookie and X-Profile-Id
    assert mine.headers["cache-control"].startswith("private")
    assert "X-Profile-Id" in mine.headers["vary"] and "Cookie" in mine.headers["vary"]
    assert u.get("/catalog/recommended").headers["cache-control"] == "no-store"


def test_request_id_is_sanitised(make_user):
    u = make_user()
    good = u.get("/auth/me", headers={"X-Request-ID": "abc-12345_trace"})
    assert good.headers["x-request-id"] == "abc-12345_trace"
    bad = u.get("/auth/me", headers={"X-Request-ID": "x y<script>"})
    assert re.fullmatch(r"[0-9a-f]{16}", bad.headers["x-request-id"])


def test_csrf_failure_does_not_print_tokens(make_user, capsys):
    u = make_user()
    u.csrf = "wrong-token-value"
    assert u.post("/profiles", json={"name": "Z"}).status_code == 403
    out = capsys.readouterr().out
    assert "wrong-token-value" not in out and "CSRF" not in out


def test_api_debug_stub_endpoint_removed():
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).get("/v1/models").status_code == 404


# ------------------------------------------------------------------ production configuration guard
def _prod(**kw):
    base = dict(env="production", database_url="postgresql+psycopg://ott:Xk29-very-long-secret@db/ott",
                cors_origins=["https://watch.example.com"], frontend_url="https://watch.example.com",
                redis_url="redis://redis:6379/0", country_header="CF-IPCountry", smtp_host="smtp.example.com",
                enable_docs=False)
    return Settings(_env_file=None, **{**base, **kw})


def test_production_guard_accepts_a_sound_config():
    fatal, warn = production_problems(_prod())
    assert fatal == [] and warn == []


@pytest.mark.parametrize("override,needle", [
    ({"database_url": "postgresql+psycopg://ott:ott@db/ott"}, "default password"),
    ({"database_url": "postgresql+psycopg://postgres:2205@db/ott"}, "default password"),
    ({"cors_origins": ["*"]}, "CORS_ORIGINS"),
    ({"cors_origins": ["http://localhost:5173"]}, "CORS_ORIGINS"),
    ({"frontend_url": "http://watch.example.com"}, "FRONTEND_URL"),
    ({"cookie_secure": False}, "COOKIE_SECURE"),
    ({"demo_sample_video": True}, "DEMO_SAMPLE_VIDEO"),
    ({"stripe_secret_key": "sk_test_x"}, "STRIPE_WEBHOOK_SECRET"),
])
def test_production_guard_rejects_unsafe_settings(override, needle):
    fatal, _ = production_problems(_prod(**override))
    assert any(needle in f for f in fatal), fatal


def test_production_guard_warns_about_degraded_but_safe_settings():
    _, warn = production_problems(_prod(redis_url="", country_header="", smtp_host="", enable_docs=True))
    assert len(warn) == 4


def test_app_refuses_to_start_with_unsafe_production_settings(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "get_settings", lambda: _prod(database_url="postgresql+psycopg://ott:ott@db/ott"))
    with pytest.raises(RuntimeError, match="default password"):
        main.create_app()


# ------------------------------------------------------------------ passwords and tokens
@pytest.mark.parametrize("pw", ["aaaaaaaaaaaa", "Password1234", "1q2w3e4r5t", "short"])
def test_weak_passwords_rejected(pw):
    assert validate_password_strength(pw)


def test_a_long_passphrase_is_accepted():
    assert validate_password_strength("correct horse battery staple") is None


def test_reset_token_cannot_be_claimed_twice(make_user, mails, db):
    from app.models import EmailToken
    from app.routers.auth import _consume_token
    from fastapi import HTTPException
    make_user("tok@example.com", verify=False)
    raw = re.search(r"token=([\w-]+)", mails[-1][2]).group(1)
    _consume_token(db, raw, "verify")
    db.commit()
    with pytest.raises(HTTPException):
        _consume_token(db, raw, "verify")
    assert db.query(EmailToken).filter(EmailToken.used_at.is_not(None)).count() == 1


# ------------------------------------------------------------------ redis outage handling
class _BrokenRedis:
    def pipeline(self):
        raise ConnectionError("down")

    def get(self, *_):
        raise ConnectionError("down")

    def ping(self):
        raise ConnectionError("down")


def test_rate_limit_survives_a_redis_outage_and_retries_redis(monkeypatch):
    from app import ratelimit
    cache._redis = _BrokenRedis()
    cache._retry_at = 0.0
    monkeypatch.setattr(get_settings(), "redis_url", "redis://unreachable:6379/0")
    connects = []
    monkeypatch.setattr(cache, "_connect", lambda: connects.append(1))
    try:
        assert ratelimit._hit("t:outage", 60) == 1  # falls back to the local counter for this call
        assert ratelimit._hit("t:outage", 60) == 2
        assert cache._redis is None and cache._retry_at > time.time()
        assert cache.ping() is False  # configured but unreachable is reported, not hidden
        cache._retry_at = 0.0
        cache.redis()
        assert connects  # not switched off for the life of the process: it tries again
    finally:
        cache._redis = None
        cache._retry_at = 0.0


def test_redis_not_configured_is_not_an_outage():
    assert cache.ping() is True


# ------------------------------------------------------------------ worker
def test_worker_runs_jobs_isolates_failures_and_stops_gracefully():
    calls = []

    def ok():
        calls.append("ok")
        worker._stop.set()  # stop after the first pass

    def boom():
        calls.append("boom")
        raise RuntimeError("job failed")

    worker._stop.clear()
    try:
        worker.loop(tick_s=0.01, schedule={"a": (boom, 3600), "b": (ok, 3600)})
    finally:
        worker._stop.clear()
    assert calls == ["boom", "ok"]  # one failing job does not stop the others


def test_worker_run_job_reports_outcome():
    assert worker.run_job("x", lambda: None) is True
    assert worker.run_job("x", lambda: 1 / 0) is False


# ------------------------------------------------------------------ rights re-checked during playback
def test_heartbeat_stops_a_stream_whose_right_was_revoked(make_user, db):
    t = mk_title(db)
    mk_asset(db, t)
    right = mk_right(db, t)
    u = make_user()
    sid = u.post("/playback/sessions", json={"title_id": str(t.id)}).json()["session_id"]
    assert u.post(f"/playback/sessions/{sid}/heartbeat").status_code == 200
    right.status = "revoked"
    db.commit()
    r = u.post(f"/playback/sessions/{sid}/heartbeat")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_verified"
    assert u.post(f"/playback/sessions/{sid}/heartbeat").status_code == 410  # the session is closed for good
