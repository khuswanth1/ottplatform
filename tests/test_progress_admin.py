from app.models import WatchProgress
from helpers import mk_asset, mk_episode, mk_right, mk_title


def test_progress_throttles_writes(make_user, db):
    u, t = make_user(), mk_title(db)
    body = {"title_id": str(t.id), "position_seconds": 100, "duration_seconds": 6000}
    assert u.put("/watch-progress", json=body).json()["message"] == "saved"
    assert u.put("/watch-progress", json={**body, "position_seconds": 102}).json()["message"] == "unchanged"
    assert u.put("/watch-progress", json={**body, "position_seconds": 130}).json()["message"] == "saved"
    assert db.query(WatchProgress).count() == 1


def test_continue_watching_and_history(make_user, db):
    u = make_user()
    m = mk_title(db, "Movie")
    s = mk_title(db, "Show", type_="series")
    e1, e2 = mk_episode(db, s, 1), mk_episode(db, s, 2)
    u.put("/watch-progress", json={"title_id": str(m.id), "position_seconds": 600, "duration_seconds": 6000})
    u.put("/watch-progress", json={"title_id": str(s.id), "episode_id": str(e1.id), "position_seconds": 2900, "duration_seconds": 3000})
    cw = u.get("/watch-progress").json()
    by = {x["title"]["name"]: x for x in cw}
    assert by["Movie"]["position_seconds"] == 600
    assert by["Show"]["episode_id"] == str(e2.id) and by["Show"]["position_seconds"] == 0  # finished ep1 -> next
    u.put("/watch-progress", json={"title_id": str(m.id), "position_seconds": 5900, "duration_seconds": 6000})
    assert "Movie" not in {x["title"]["name"] for x in u.get("/watch-progress").json()}  # completed
    assert {x["title"]["name"] for x in u.get("/watch-progress?history=true").json()} == {"Movie", "Show"}


def test_progress_validation(make_user, db):
    u = make_user()
    s = mk_title(db, "Show", type_="series")
    assert u.put("/watch-progress", json={"title_id": str(s.id), "position_seconds": 1, "duration_seconds": 10}).status_code == 400
    assert u.put("/watch-progress", json={"title_id": str(s.id), "position_seconds": -5, "duration_seconds": 10}).status_code == 422


def test_progress_isolated_between_accounts(make_user, db):
    a, b, t = make_user("a@example.com"), make_user("b@example.com"), mk_title(db)
    a.put("/watch-progress", json={"title_id": str(t.id), "position_seconds": 50, "duration_seconds": 100})
    assert b.get("/watch-progress").json() == []


# ---------------- admin ----------------
def test_admin_full_rights_workflow(make_admin, make_user, db):
    admin = make_admin()
    tid = admin.post("/admin/titles", json={"type": "movie", "name": "Night of the Living Public Domain", "status": "published",
                                            "genres": ["Horror"], "release_date": "1968-10-01"}).json()["id"]
    # rights always start unverified, so nothing is playable yet
    rid = admin.post("/admin/title-rights", json={"title_id": tid, "license_type": "public_domain", "territories": ["us", "IN"],
                                                  "evidence_url": "https://example.org/proof"}).json()["id"]
    assert admin.get("/admin/title-rights").json()[0]["status"] == "unverified"
    assert admin.get("/admin/title-rights").json()[0]["territories"] == ["US", "IN"]
    aid = admin.post("/admin/media-assets", json={"title_id": tid, "kind": "hls", "url": "https://cdn.example.com/x.m3u8",
                                                  "subtitles": [{"lang": "en", "label": "English", "url": "https://cdn.example.com/en.vtt"}]}).json()["id"]
    viewer = make_user("viewer@example.com")
    assert viewer.post("/playback/sessions", json={"title_id": tid}).status_code == 403
    assert admin.post(f"/admin/title-rights/{rid}/verify").status_code == 200
    r = viewer.post("/playback/sessions", json={"title_id": tid})
    assert r.status_code == 201 and r.json()["subtitles"][0]["lang"] == "en"
    # revoking takes effect immediately
    assert admin.patch(f"/admin/title-rights/{rid}", json={"status": "revoked"}).status_code == 200
    assert viewer.post("/playback/sessions", json={"title_id": tid}).status_code == 403
    # disabling the asset / archiving the title also stops playback
    admin.patch(f"/admin/title-rights/{rid}", json={"status": "unverified"})
    admin.post(f"/admin/title-rights/{rid}/verify")
    assert admin.patch(f"/admin/media-assets/{aid}", json={"is_active": False}).status_code == 200
    assert viewer.post("/playback/sessions", json={"title_id": tid}).status_code == 404
    actions = [a["action"] for a in admin.get("/admin/audit-logs").json()]
    assert {"title.create", "right.create", "right.verify", "asset.create", "right.update"} <= set(actions)


def test_verify_requires_evidence_and_concrete_license(make_admin, db):
    admin = make_admin()
    t = mk_title(db)
    rid = admin.post("/admin/title-rights", json={"title_id": str(t.id), "license_type": "unknown"}).json()["id"]
    assert admin.post(f"/admin/title-rights/{rid}/verify").status_code == 422


def test_changing_legal_basis_resets_verification(make_admin, db):
    admin = make_admin()
    t = mk_title(db)
    r = mk_right(db, t)
    out = admin.patch(f"/admin/title-rights/{r.id}", json={"evidence_url": "https://new.example/proof"}).json()
    assert out["status"] == "unverified"


def test_admin_asset_validation(make_admin, db):
    admin = make_admin()
    t = mk_title(db)
    bad = lambda **kw: admin.post("/admin/media-assets", json={"title_id": str(t.id), "kind": "hls", **kw}).status_code
    assert bad(url="http://insecure.example/a.m3u8") == 422  # https only
    assert bad(url="javascript:alert(1)") == 422
    assert admin.post("/admin/media-assets", json={"title_id": str(t.id), "kind": "embed", "url": "https://evil.example/e"}).status_code == 422
    s = mk_title(db, "Series", type_="series")
    assert admin.post("/admin/media-assets", json={"title_id": str(s.id), "kind": "hls", "url": "https://cdn.example.com/a.m3u8"}).status_code == 422
    e = mk_episode(db, mk_title(db, "Other", type_="series"))
    assert admin.post("/admin/media-assets", json={"title_id": str(s.id), "episode_id": str(e.id), "kind": "hls",
                                                   "url": "https://cdn.example.com/a.m3u8"}).status_code == 422


def test_admin_title_edit_locks_from_provider_overwrite(make_admin, upstream, db):
    from conftest import Browser
    admin = make_admin()
    tid = Browser().get("/catalog?section=popular&type=movie").json()["items"][0]["id"]
    assert admin.patch(f"/admin/titles/{tid}", json={"name": "Curated Name"}).status_code == 200
    from app.cache import cache
    cache.clear()
    from app.models import Title
    t = db.get(Title, __import__("uuid").UUID(tid))
    t.metadata_synced_at = None
    db.commit()
    Browser().get("/catalog?section=popular&type=movie")
    db.expire_all()
    assert db.get(Title, __import__("uuid").UUID(tid)).name == "Curated Name"


def test_admin_publish_and_archive(make_admin, make_user, db):
    admin = make_admin()
    tid = admin.post("/admin/titles", json={"type": "movie", "name": "Hidden Draft"}).json()["id"]
    user = make_user("v@example.com")
    assert user.get(f"/titles/{tid}").status_code == 404  # drafts are invisible
    admin.patch(f"/admin/titles/{tid}", json={"status": "published"})
    assert user.get(f"/titles/{tid}").status_code == 200
    admin.delete(f"/admin/titles/{tid}")
    assert user.get(f"/titles/{tid}").status_code == 404


def test_archive_import_is_draft_with_unverified_rights(make_admin, upstream, db):
    from app.models import TitleRight
    from app.providers.registry import get_registry
    import httpx
    arch = next(p for p in get_registry().free)
    arch.http._client._transport.handler = lambda r: httpx.Response(200, json={
        "metadata": {"title": "Old Film", "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/"},
        "files": [{"name": "old.mp4", "format": "h.264"}]})
    admin = make_admin()
    assert admin.get("/admin/archive/old_film/files").json()["suggested_license_type"] == "public_domain"
    out = admin.post("/admin/titles/import", json={"provider": "archive", "external_id": "old_film"}).json()
    assert out["status"] == "draft"
    r = db.query(TitleRight).one()
    assert r.status == "unverified" and r.source == "archive"


def test_admin_user_plan_management(make_admin, make_user, db):
    from app.models import User
    admin = make_admin()
    make_user("p@example.com")
    uid = db.query(User).filter_by(email="p@example.com").one().id
    assert admin.patch(f"/admin/users/{uid}", json={"plan": "premium"}).status_code == 200
    db.expire_all()
    assert db.get(User, uid).plan == "premium"


def test_retention_job_prunes_old_rows(make_user, db):
    from datetime import datetime, timedelta, timezone

    from app import retention
    from app.models import AuditLog, AuthSession
    u = make_user()
    db.add(AuditLog(action="old", entity_type="x", created_at=datetime.now(timezone.utc) - timedelta(days=400)))
    db.add(AuditLog(action="new", entity_type="x"))
    db.commit()
    out = retention.run()
    assert out["audit_logs"] == 1
    assert db.query(AuthSession).count() == 1  # live session untouched


def test_hide_history_entry_and_bring_it_back(make_user, db):
    from helpers import mk_episode, mk_title
    u, m = make_user(), mk_title(db, "Movie")
    u.put("/watch-progress", json={"title_id": str(m.id), "position_seconds": 600, "duration_seconds": 6000})
    entry = u.get("/watch-progress?history=true").json()[0]
    assert u.delete(f"/watch-progress/{entry['id']}").status_code == 200
    assert u.delete(f"/watch-progress/{entry['id']}").status_code == 200  # idempotent
    assert u.get("/watch-progress?history=true").json() == [] and u.get("/watch-progress").json() == []  # also leaves Continue Watching
    # same position again would normally be skipped as "unchanged"; a hidden row must still come back
    assert u.put("/watch-progress", json={"title_id": str(m.id), "position_seconds": 600, "duration_seconds": 6000}).json()["message"] == "saved"
    assert len(u.get("/watch-progress?history=true").json()) == 1


def test_hide_whole_series_and_ownership(make_user, db):
    from helpers import mk_episode, mk_title
    a, b = make_user("a@example.com"), make_user("b@example.com")
    s = mk_title(db, "Show", type_="series")
    e1, e2 = mk_episode(db, s, 1), mk_episode(db, s, 2)
    for e in (e1, e2):
        a.put("/watch-progress", json={"title_id": str(s.id), "episode_id": str(e.id), "position_seconds": 100, "duration_seconds": 3000})
    b.put("/watch-progress", json={"title_id": str(s.id), "episode_id": str(e1.id), "position_seconds": 100, "duration_seconds": 3000})
    mine = a.get("/watch-progress?history=true").json()
    assert len(mine) == 2
    assert b.delete(f"/watch-progress/{mine[0]['id']}").status_code == 404  # not B's entry
    assert len(a.get("/watch-progress?history=true").json()) == 2
    assert a.delete(f"/watch-progress?title_id={s.id}").status_code == 200
    assert a.get("/watch-progress?history=true").json() == []
    assert len(b.get("/watch-progress?history=true").json()) == 1  # other profiles untouched


def test_get_title_progress(make_user, db):
    u = make_user()
    m = mk_title(db, "Direct Title")
    assert u.get(f"/watch-progress/title/{m.id}").json() is None
    u.put("/watch-progress", json={"title_id": str(m.id), "position_seconds": 450, "duration_seconds": 3600})
    res = u.get(f"/watch-progress/title/{m.id}").json()
    assert res is not None
    assert res["position_seconds"] == 450
    assert res["completed"] is False
