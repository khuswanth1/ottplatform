from helpers import mk_episode, mk_title


def put(admin, title, kind="intro", start=10, end=70, episode=None):
    body = {"title_id": str(title.id), "kind": kind, "start_s": start, "end_s": end}
    if episode:
        body["episode_id"] = str(episode.id)
    return admin.put("/admin/markers", json=body)


def test_admin_sets_and_replaces_a_movie_marker_and_viewers_read_it(make_admin, make_user, db):
    admin, viewer, t = make_admin(), make_user(), mk_title(db)
    assert put(admin, t).status_code == 200
    assert put(admin, t, start=20, end=80).status_code == 200            # same kind: replaced, not duplicated
    put(admin, t, kind="credits", start=5000, end=5400)
    got = viewer.get(f"/titles/{t.id}/markers").json()
    assert [(m["kind"], m["start_s"], m["end_s"]) for m in got] == [("intro", 20, 80), ("credits", 5000, 5400)]
    assert len(admin.get(f"/admin/markers?title_id={t.id}").json()) == 2


def test_series_markers_are_per_episode(make_admin, make_user, db):
    admin, viewer = make_admin(), make_user()
    s = mk_title(db, "Show", type_="series")
    e1, e2 = mk_episode(db, s, 1), mk_episode(db, s, 2)
    put(admin, s, episode=e1, start=0, end=45)
    put(admin, s, episode=e2, start=30, end=95)
    put(admin, s, kind="recap", episode=e2, start=0, end=30)
    assert [(m["kind"], m["end_s"]) for m in viewer.get(f"/titles/{s.id}/markers?episode_id={e1.id}").json()] == [("intro", 45)]
    assert [(m["kind"], m["end_s"]) for m in viewer.get(f"/titles/{s.id}/markers?episode_id={e2.id}").json()] == [("recap", 30), ("intro", 95)]
    assert viewer.get(f"/titles/{s.id}/markers").json() == []            # a series needs an episode to answer


def test_marker_validation(make_admin, db):
    admin, movie = make_admin(), mk_title(db)
    show, other = mk_title(db, "Show", type_="series"), mk_title(db, "Other", type_="series")
    foreign = mk_episode(db, other, 1)
    assert put(admin, movie, start=50, end=50).status_code == 400
    assert put(admin, movie, start=-1, end=10).status_code == 422
    assert put(admin, show).status_code == 400                           # series without an episode
    assert put(admin, show, episode=foreign).status_code == 400          # episode of another title
    assert put(admin, movie, episode=mk_episode(db, show, 1)).status_code == 400   # movie with an episode
    assert admin.put("/admin/markers", json={"title_id": str(movie.id), "kind": "ending", "start_s": 1, "end_s": 2}).status_code == 422
    assert admin.put("/admin/markers", json={"title_id": "00000000-0000-0000-0000-000000000000", "kind": "intro", "start_s": 1, "end_s": 2}).status_code == 404


def test_delete_marker_and_audit(make_admin, make_user, db):
    admin, viewer, t = make_admin(), make_user(), mk_title(db)
    m = put(admin, t).json()
    assert admin.delete(f"/admin/markers/{m['id']}").status_code == 200
    assert admin.delete(f"/admin/markers/{m['id']}").status_code == 404
    assert viewer.get(f"/titles/{t.id}/markers").json() == []
    actions = [a["action"] for a in admin.get("/admin/audit-logs").json()]
    assert "marker.set" in actions and "marker.remove" in actions


def test_only_admins_write_markers_and_drafts_stay_hidden(make_admin, make_user, db):
    from conftest import Browser
    admin, user, t = make_admin(), make_user(), mk_title(db)
    body = {"title_id": str(t.id), "kind": "intro", "start_s": 1, "end_s": 9}
    assert Browser().put("/admin/markers", json=body).status_code == 401
    assert user.put("/admin/markers", json=body).status_code == 403
    assert user.delete(f"/admin/markers/{put(admin, t).json()['id']}").status_code == 403
    draft = mk_title(db, "Draft", status="draft")
    assert user.get(f"/titles/{draft.id}/markers").status_code == 404
