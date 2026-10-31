from helpers import mk_title


def test_cannot_use_another_users_profile(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    b.profile = a.profile  # B presents A's profile id
    assert b.get("/watchlist").status_code == 404
    assert b.get("/watch-progress").status_code == 404
    assert b.get("/catalog/home").status_code == 404


def test_cannot_modify_or_delete_another_users_profile(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    assert b.patch(f"/profiles/{a.profile}", json={"name": "Hacked"}).status_code == 404
    assert b.delete(f"/profiles/{a.profile}").status_code == 404
    assert [p["name"] for p in a.get("/profiles").json()] == ["Me"]
    assert [p["id"] for p in b.get("/profiles").json()] != [a.profile]


def test_watchlists_are_per_profile(make_user, db):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    t = mk_title(db)
    assert a.put(f"/watchlist/{t.id}", json={"kind": "favorite"}).status_code == 200
    assert a.get("/watchlist/ids").json()["favorite"] == [str(t.id)]
    assert b.get("/watchlist/ids").json() == {"watchlist": [], "favorite": []}
    assert b.get("/watchlist?kind=favorite").json()["items"] == []
    a.profile = a.post("/profiles", json={"name": "Second"}).json()["id"]
    assert a.get("/watchlist/ids").json()["favorite"] == []  # second profile of the same user is isolated too


def test_watchlist_idempotent_and_removal(make_user, db):
    u, t = make_user(), mk_title(db)
    assert u.put(f"/watchlist/{t.id}").status_code == 200 and u.put(f"/watchlist/{t.id}").status_code == 200
    assert len(u.get("/watchlist").json()["items"]) == 1
    u.delete(f"/watchlist/{t.id}")
    assert u.get("/watchlist").json()["items"] == []


def test_admin_endpoints_are_protected(make_user, db):
    from conftest import Browser
    t = mk_title(db)
    anon, user = Browser(), make_user("u@example.com")
    for method, url in (("get", "/admin/titles"), ("get", "/admin/media-assets"), ("get", "/admin/title-rights"),
                        ("get", "/admin/audit-logs"), ("post", f"/admin/title-rights/{t.id}/verify")):
        assert getattr(anon, method)(url).status_code == 401, url
        assert getattr(user, method)(url).status_code == 403, url
    r = user.post("/admin/media-assets", json={"title_id": str(t.id), "kind": "hls", "url": "https://x.example/a.m3u8"})
    assert r.status_code == 403


def test_profile_limit(make_user):
    u = make_user()
    for i in range(4):
        assert u.post("/profiles", json={"name": f"P{i}"}).status_code == 201
    assert u.post("/profiles", json={"name": "Too many"}).status_code == 409


def test_cannot_delete_last_profile(make_user):
    u = make_user()
    assert u.delete(f"/profiles/{u.profile}").status_code == 409


def test_invalid_profile_header(make_user):
    u = make_user()
    u.profile = "not-a-uuid"
    assert u.get("/watchlist").status_code == 400


def test_oversized_body_rejected(make_user):
    u = make_user()
    r = u.post("/profiles", content=b"x" * (300 * 1024), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_avatar_must_be_one_of_the_known_ids(make_user):
    u = make_user()
    ok = u.post("/profiles", json={"name": "Art", "avatar": "avatar-12"})
    assert ok.status_code == 201 and ok.json()["avatar"] == "avatar-12"
    for bad in ("avatar-0", "avatar-25", "avatar-99", "avatar-٣", "avatar-3 ", "../x", "AVATAR-3"):
        assert u.post("/profiles", json={"name": f"Bad {bad}", "avatar": bad}).status_code == 422, bad
    assert u.patch(f"/profiles/{ok.json()['id']}", json={"avatar": "avatar-24"}).status_code == 200
    assert u.patch(f"/profiles/{ok.json()['id']}", json={"avatar": "avatar-25"}).status_code == 422
