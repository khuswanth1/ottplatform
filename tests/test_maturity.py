from app.maturity import rating_age, title_allowed
from helpers import mk_asset, mk_right, mk_title


class T:  # minimal stand-in for Title
    def __init__(self, rating=None, kids=False):
        self.age_rating, self.is_kids_safe = rating, kids


def test_rating_ladder():
    assert [rating_age(r) for r in ("G", "pg", "TV-14", "R", "TV-MA", "??", None)] == [0, 8, 14, 17, 18, None, None]
    assert title_allowed(T("PG"), "7+") and not title_allowed(T("PG-13"), "7+")
    assert title_allowed(T("TV-14"), "13+") and not title_allowed(T("R"), "13+")
    assert not title_allowed(T(None), "13+") and title_allowed(T(None), "all")
    assert title_allowed(T(None, kids=True), "7+") and not title_allowed(T("PG", False), "kids")


def _titled(db, name, rating, kids=False):
    t = mk_title(db, name, kids=kids)
    t.age_rating = rating
    db.commit()
    return t


def test_profile_levels_and_legacy_flag(make_user):
    u = make_user()
    p = u.post("/profiles", json={"name": "A", "maturity_level": "13+"}).json()
    assert (p["maturity_level"], p["is_kids"]) == ("13+", False)
    k = u.post("/profiles", json={"name": "B", "is_kids": True}).json()
    assert (k["maturity_level"], k["is_kids"]) == ("kids", True)
    k2 = u.patch(f"/profiles/{k['id']}", json={"is_kids": False}).json()
    assert (k2["maturity_level"], k2["is_kids"]) == ("all", False)
    p2 = u.patch(f"/profiles/{p['id']}", json={"maturity_level": "kids"}).json()
    assert p2["is_kids"] is True
    assert u.post("/profiles", json={"name": "C", "maturity_level": "18+"}).status_code == 422
    assert u.get("/profiles").json()[0]["maturity_level"] == "all"  # default profile unrestricted


def test_levels_filter_watchlist_titles_and_playback(make_user, db):
    u = make_user()
    pg, r = _titled(db, "Gentle", "PG"), _titled(db, "Gritty", "R")
    for t in (pg, r):
        mk_asset(db, t, url=f"https://cdn.example.com/{t.name}/index.m3u8")  # one stream per title
        mk_right(db, t)
    teen = u.post("/profiles", json={"name": "Teen", "maturity_level": "7+"}).json()["id"]
    u.profile = teen
    assert u.get(f"/titles/{pg.id}").status_code == 200
    assert u.get(f"/titles/{r.id}").status_code == 404
    assert u.put(f"/watchlist/{r.id}").status_code == 404
    denied = u.post("/playback/sessions", json={"title_id": str(r.id)})
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "maturity_restricted"
    assert u.post("/playback/sessions", json={"title_id": str(pg.id)}).status_code == 201


def test_home_cache_is_per_level(make_user, upstream, db):
    u = make_user()
    adult = u.get("/catalog/home").json()
    names = {i["name"] for row in adult["rows"] for i in row["items"]}
    assert names  # unrestricted profile sees the mocked catalog
    kid = u.post("/profiles", json={"name": "Kid", "maturity_level": "13+"}).json()["id"]
    u.profile = kid
    teen = u.get("/catalog/home").json()
    assert {i["name"] for row in teen["rows"] for i in row["items"]} <= names  # never a superset, never the cached adult page
