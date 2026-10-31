from helpers import days, mk_title


def test_featured_empty_by_default(make_user):
    assert make_user().get("/catalog/featured").json() == []


def test_admin_curates_and_viewer_sees_in_order(make_admin, make_user, db):
    admin, viewer = make_admin(), make_user()
    a, b = mk_title(db, "Alpha"), mk_title(db, "Beta")
    assert admin.post("/admin/featured", json={"title_id": str(b.id), "position": 2}).status_code == 201
    assert admin.post("/admin/featured", json={"title_id": str(a.id), "position": 1}).status_code == 201
    assert [t["name"] for t in viewer.get("/catalog/featured").json()] == ["Alpha", "Beta"]
    # same title + country updates in place instead of duplicating
    admin.post("/admin/featured", json={"title_id": str(a.id), "position": 5})
    assert [t["name"] for t in viewer.get("/catalog/featured").json()] == ["Beta", "Alpha"]
    assert len(admin.get("/admin/featured").json()) == 2


def test_featured_respects_country_and_window(make_admin, make_user, db):
    admin, viewer = make_admin(), make_user()
    t1, t2, t3 = mk_title(db, "Here"), mk_title(db, "Elsewhere"), mk_title(db, "Expired")
    admin.post("/admin/featured", json={"title_id": str(t1.id), "country": "us"})
    admin.post("/admin/featured", json={"title_id": str(t2.id), "country": "GB"})
    admin.post("/admin/featured", json={"title_id": str(t3.id), "ends_at": days(-1).isoformat()})
    assert [t["name"] for t in viewer.get("/catalog/featured").json()] == ["Here"]  # default country is US
    viewer.country = "GB"
    assert [t["name"] for t in viewer.get("/catalog/featured").json()] == ["Elsewhere"]


def test_featured_hides_non_kids_titles_from_kids_profile(make_admin, make_user, db):
    admin, viewer = make_admin(), make_user()
    t = mk_title(db, "Grown Up")
    admin.post("/admin/featured", json={"title_id": str(t.id)})
    kid = viewer.post("/profiles", json={"name": "Kid", "is_kids": True}).json()["id"]
    viewer.profile = kid
    assert viewer.get("/catalog/featured").json() == []


def test_featured_validation_and_permissions(make_admin, make_user, db):
    admin, user = make_admin(), make_user()
    draft = mk_title(db, "Draft", status="draft")
    assert admin.post("/admin/featured", json={"title_id": str(draft.id)}).status_code == 400
    ok = mk_title(db, "Ok")
    assert admin.post("/admin/featured", json={"title_id": str(ok.id), "starts_at": days(2).isoformat(), "ends_at": days(1).isoformat()}).status_code == 400
    assert admin.post("/admin/featured", json={"title_id": str(ok.id), "country": "USA"}).status_code == 422
    assert user.post("/admin/featured", json={"title_id": str(ok.id)}).status_code == 403
    assert user.get("/admin/featured").status_code == 403


def test_featured_delete(make_admin, make_user, db):
    admin, viewer = make_admin(), make_user()
    t = mk_title(db, "Gone")
    admin.post("/admin/featured", json={"title_id": str(t.id)})
    fid = admin.get("/admin/featured").json()[0]["id"]
    assert admin.delete(f"/admin/featured/{fid}").status_code == 200
    assert viewer.get("/catalog/featured").json() == []
    assert admin.delete(f"/admin/featured/{fid}").status_code == 404
