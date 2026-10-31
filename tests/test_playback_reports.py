from helpers import mk_title
from conftest import Browser
from app.models import PlaybackReport


def _report(u, t, **kw):
    return u.post("/playback/reports", json={"title_id": str(t.id), "kind": "no_sound", **kw})


def test_report_is_stored_and_a_repeat_updates_it(make_user, db):
    u, t = make_user(), mk_title(db)
    r = _report(u, t, note="silent after 10 min", position_seconds=600)
    assert r.status_code == 201, r.text
    r2 = _report(u, t, note="still silent", position_seconds=700)
    assert r2.json()["id"] == r.json()["id"]
    assert db.query(PlaybackReport).count() == 1
    assert db.query(PlaybackReport).one().note == "still silent"
    assert _report(u, t, kind="buffering").status_code == 201  # different kind is its own report
    assert db.query(PlaybackReport).count() == 2


def test_report_validation(make_user, db):
    u, t = make_user(), mk_title(db)
    assert _report(u, t, kind="nope").status_code == 422
    assert _report(u, t, note="x" * 501).status_code == 422
    assert _report(u, t, position_seconds=-1).status_code == 422
    assert u.post("/playback/reports", json={"title_id": "00000000-0000-0000-0000-000000000000", "kind": "other"}).status_code == 404
    draft = mk_title(db, "Draft", status="draft")
    assert _report(u, draft).status_code == 404
    other = mk_title(db, "Other")
    assert _report(u, t, episode_id=str(other.id)).status_code == 400  # not an episode of this title


def test_report_requires_login(db):
    t = mk_title(db)
    assert Browser().post("/playback/reports", json={"title_id": str(t.id), "kind": "other"}).status_code in (401, 403)


def test_admin_lists_and_resolves_but_viewers_cannot(make_admin, make_user, db):
    admin, u, t = make_admin(), make_user(), mk_title(db)
    rid = _report(u, t, note="no picture").json()["id"]
    assert u.get("/admin/playback-reports").status_code == 403
    assert u.post(f"/admin/playback-reports/{rid}/resolve").status_code == 403
    items = admin.get("/admin/playback-reports").json()["items"]
    assert [i["id"] for i in items] == [rid] and items[0]["note"] == "no picture"
    assert admin.post(f"/admin/playback-reports/{rid}/resolve").json()["status"] == "resolved"
    assert admin.get("/admin/playback-reports").json()["total"] == 0
    assert admin.get("/admin/playback-reports?status=resolved").json()["total"] == 1
    assert admin.post("/admin/playback-reports/00000000-0000-0000-0000-000000000000/resolve").status_code == 404
