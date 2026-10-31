from app.models import Genre, TitleGenre
from app.services.catalog import slugify
from helpers import mk_title


def tag(db, title, *names):
    for n in names:
        g = db.query(Genre).filter_by(name=n).first() or Genre(name=n, slug=slugify(n))
        db.add(g)
        db.flush()
        db.add(TitleGenre(title_id=title.id, genre_id=g.id))
    db.commit()


def ids(r):
    return [x["id"] for x in r.json()]


def test_similar_ranks_by_shared_genres_and_same_type(make_user, db):
    u = make_user()
    base, both, one = mk_title(db, "Base"), mk_title(db, "Both"), mk_title(db, "One")
    other_type, draft, none = mk_title(db, "Show", type_="series"), mk_title(db, "Draft", status="draft"), mk_title(db, "None")
    tag(db, base, "Action", "Drama")
    tag(db, both, "Action", "Drama")
    tag(db, one, "Drama")
    tag(db, other_type, "Action", "Drama")
    tag(db, draft, "Action", "Drama")
    tag(db, none, "Comedy")
    r = u.get(f"/titles/{base.id}/similar")
    assert r.status_code == 200
    assert ids(r) == [str(both.id), str(one.id)]  # not itself, not another type, not a draft, not unrelated


def test_similar_empty_without_genres_and_404_for_unknown(make_user, db):
    u, t = make_user(), mk_title(db)
    assert u.get(f"/titles/{t.id}/similar").json() == []
    assert u.get("/titles/00000000-0000-0000-0000-000000000000/similar").status_code == 404


def test_similar_for_kids_profile_only_family_safe(make_user, db):
    u = make_user()
    base, safe, adult = mk_title(db, "Base", kids=True), mk_title(db, "Safe", kids=True), mk_title(db, "Grown")
    for t in (base, safe, adult):
        tag(db, t, "Animation")
    u.profile = u.post("/profiles", json={"name": "Kid", "is_kids": True}).json()["id"]
    assert ids(u.get(f"/titles/{base.id}/similar")) == [str(safe.id)]


def test_suggest_prefix_match_and_limits(make_user, db):
    u = make_user()
    for i in range(10):
        mk_title(db, f"Star {i}")
    mk_title(db, "Lone Star")
    mk_title(db, "Star Draft", status="draft")
    r = u.get("/catalog/suggest", params={"q": "Star"})
    assert r.status_code == 200
    names = [x["name"] for x in r.json()]
    assert len(names) == 8 and all(n.startswith("Star ") for n in names) and "Star Draft" not in names
    assert [x["name"] for x in u.get("/catalog/suggest", params={"q": "lone"}).json()] == ["Lone Star"]  # case-insensitive prefix
    assert u.get("/catalog/suggest", params={"q": "S"}).status_code == 422
    assert u.get("/catalog/suggest", params={"q": "50%"}).json() == []  # wildcard chars are not special


def test_suggest_hides_adult_titles_from_kids(make_user, db):
    u = make_user()
    mk_title(db, "Moana Jr", kids=True)
    mk_title(db, "Moana Noir")
    u.profile = u.post("/profiles", json={"name": "Kid", "is_kids": True}).json()["id"]
    assert [x["name"] for x in u.get("/catalog/suggest", params={"q": "moana"}).json()] == ["Moana Jr"]
