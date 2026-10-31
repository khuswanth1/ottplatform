from test_similar_suggest import tag
from helpers import mk_title


def names(r):
    return [x["name"] for x in r.json()]


def setup(db):
    t = {n: mk_title(db, n) for n in ("Seen", "Liked", "Disliked", "Both", "Action", "Comedy", "Horror", "Mixed", "Draft")}
    db.query(type(t["Draft"])).filter_by(id=t["Draft"].id).update({"status": "draft"})
    tag(db, t["Seen"], "Action")
    tag(db, t["Liked"], "Drama", "Action")
    tag(db, t["Disliked"], "Horror")
    tag(db, t["Both"], "Drama", "Action")
    tag(db, t["Action"], "Action")
    tag(db, t["Comedy"], "Comedy")
    tag(db, t["Horror"], "Horror")
    tag(db, t["Mixed"], "Action", "Horror")
    tag(db, t["Draft"], "Action", "Drama")
    return t


def test_cold_start_is_empty(make_user, db):
    u = make_user()
    setup(db)
    r = u.get("/catalog/recommended")
    assert r.status_code == 200 and r.json() == []


def test_ranks_by_taste_and_skips_seen_rated_and_disliked_genres(make_user, db):
    u, t = make_user(), setup(db)
    u.put("/watch-progress", json={"title_id": str(t["Seen"].id), "position_seconds": 100, "duration_seconds": 6000})
    u.put(f"/titles/{t['Liked'].id}/rating", json={"value": 1})
    u.put(f"/titles/{t['Disliked'].id}/rating", json={"value": -1})
    # Both = Drama+Action (strongest), Action = Action only, Mixed = liked Action offset by disliked Horror
    assert names(u.get("/catalog/recommended")) == ["Both", "Action", "Mixed"]  # no Seen/Liked/Disliked, Comedy, Horror or Draft


def test_my_list_and_favorites_count_and_listed_titles_are_not_suggested(make_user, db):
    u, t = make_user(), setup(db)
    u.put(f"/watchlist/{t['Seen'].id}", json={"kind": "favorite"})
    out = names(u.get("/catalog/recommended"))
    assert "Seen" not in out and "Action" in out
    u.put(f"/watchlist/{t['Action'].id}")
    assert "Action" not in names(u.get("/catalog/recommended"))


def test_removed_activity_entry_is_not_suggested_back_and_no_longer_shapes_taste(make_user, db):
    u, t = make_user(), setup(db)
    u.put("/watch-progress", json={"title_id": str(t["Seen"].id), "position_seconds": 100, "duration_seconds": 6000})
    entry = u.get("/watch-progress?history=true").json()[0]
    u.delete(f"/watch-progress/{entry['id']}")
    assert u.get("/catalog/recommended").json() == []  # nothing else to learn from


def test_recommendations_are_per_profile_and_kids_only_see_family_titles(make_user, db):
    u = make_user()
    seen, fam, adult = mk_title(db, "Seen", kids=True), mk_title(db, "Fam", kids=True), mk_title(db, "Adult")
    for x in (seen, fam, adult):
        tag(db, x, "Animation")
    u.put("/watch-progress", json={"title_id": str(seen.id), "position_seconds": 100, "duration_seconds": 6000})
    assert set(names(u.get("/catalog/recommended"))) == {"Fam", "Adult"}
    first = u.profile
    u.profile = u.post("/profiles", json={"name": "Kid", "maturity_level": "kids"}).json()["id"]
    assert u.get("/catalog/recommended").json() == []  # the new profile has no history of its own
    u.put("/watch-progress", json={"title_id": str(seen.id), "position_seconds": 100, "duration_seconds": 6000})
    assert names(u.get("/catalog/recommended")) == ["Fam"]
    u.profile = first
    assert set(names(u.get("/catalog/recommended"))) == {"Fam", "Adult"}


def test_recommended_requires_login(make_user):
    from conftest import Browser
    assert Browser().get("/catalog/recommended").status_code == 401
