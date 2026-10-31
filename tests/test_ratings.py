from helpers import mk_title


def test_rate_change_and_clear(make_user, db):
    u, t = make_user(), mk_title(db)
    assert u.get(f"/titles/{t.id}/rating").json() == {"value": None}
    assert u.put(f"/titles/{t.id}/rating", json={"value": 1}).json() == {"value": 1}
    assert u.put(f"/titles/{t.id}/rating", json={"value": -1}).json() == {"value": -1}  # change, not duplicate
    assert u.get(f"/titles/{t.id}/rating").json() == {"value": -1}
    assert u.delete(f"/titles/{t.id}/rating").json() == {"value": None}
    assert u.delete(f"/titles/{t.id}/rating").status_code == 200  # idempotent
    assert u.get(f"/titles/{t.id}/rating").json() == {"value": None}


def test_rejects_bad_value_and_unknown_title(make_user, db):
    u, t = make_user(), mk_title(db)
    assert u.put(f"/titles/{t.id}/rating", json={"value": 5}).status_code == 422
    assert u.put("/titles/00000000-0000-0000-0000-000000000000/rating", json={"value": 1}).status_code == 404
    assert u.put(f"/titles/{mk_title(db, 'Draft', status='draft').id}/rating", json={"value": 1}).status_code == 404


def test_ratings_are_per_profile(make_user, db):
    a, b, t = make_user("a@example.com"), make_user("b@example.com"), mk_title(db)
    a.put(f"/titles/{t.id}/rating", json={"value": 2})
    assert b.get(f"/titles/{t.id}/rating").json() == {"value": None}
    a.profile = a.post("/profiles", json={"name": "Second"}).json()["id"]
    assert a.get(f"/titles/{t.id}/rating").json() == {"value": None}


def test_requires_login(make_user, db):
    from conftest import Browser
    t = mk_title(db)
    assert Browser().get(f"/titles/{t.id}/rating").status_code == 401
