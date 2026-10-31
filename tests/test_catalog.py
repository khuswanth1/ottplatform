from app.models import Title, TitleExternalId
from helpers import mk_title


def test_browse_maps_provider_results_and_dedupes(upstream, db):
    from conftest import Browser
    b = Browser()
    r = b.get("/catalog?section=popular&type=movie")
    assert r.status_code == 200, r.text
    names = [i["name"] for i in r.json()["items"]]
    assert names == ["Alpha Quest", "Beta Run", "Kid Fun", "Gamma Docu"]
    assert r.json()["items"][0]["poster_url"].endswith("/w342/p1.jpg")
    # same results again => no duplicate rows
    b.get("/catalog?section=trending&type=movie")
    assert db.query(Title).count() == 4
    assert db.query(TitleExternalId).filter_by(provider="tmdb").count() == 4


def test_provider_calls_are_cached_and_deduplicated(upstream):
    from conftest import Browser
    b = Browser()
    b.get("/catalog?section=popular&type=movie")
    n = len(upstream.calls)
    for _ in range(5):
        assert b.get("/catalog?section=popular&type=movie").status_code == 200
    assert len(upstream.calls) == n  # served from cache


def test_concurrent_identical_requests_share_one_provider_call(upstream):
    import threading

    from app.providers.registry import get_registry
    prov = get_registry().primary_metadata
    results = []
    gate = threading.Barrier(6)

    def go():
        gate.wait()
        results.append(len(prov.section("top_rated", "movie", 1, "en", None, [], None).items))

    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert results == [4] * 6
    assert upstream.count("tmdb/movie/top_rated") == 1


def test_documentary_and_language_filters(upstream):
    from conftest import Browser
    b = Browser()
    docs = b.get("/catalog/search?type=documentary").json()["items"]
    assert docs and all("Documentary" in i["genres"] for i in docs)
    te = b.get("/catalog?section=popular&type=movie&original_language=te").json()["items"]
    assert [i["name"] for i in te] == ["Beta Run"]


def test_search_text_actor_year_filters(upstream):
    from conftest import Browser
    b = Browser()
    assert [i["name"] for i in b.get("/catalog/search?q=alpha").json()["items"]] == ["Alpha Quest"]
    assert b.get("/catalog/search?actor=Some%20Actor&type=movie").json()["items"]
    assert b.get("/catalog/search?q=alpha&year=1999").json()["items"] == []  # post-filtered
    assert b.get("/catalog/search?q=").status_code == 422
    assert b.get("/catalog/search?q=" + "x" * 101).status_code == 422


def test_cross_provider_duplicates_are_merged(upstream, db):
    """A locally curated/archive title with the same name+year is merged with the TMDB hit, not duplicated."""
    from conftest import Browser
    existing = mk_title(db, "Alpha Quest", year=2020)
    Browser().get("/catalog?section=popular&type=movie")
    assert db.query(Title).filter_by(norm_name="alphaquest").count() == 1
    ids = {e.provider for e in db.get(Title, existing.id).external_ids}
    assert "tmdb" in ids


def test_provider_failure_degrades_gracefully(upstream, db):
    from conftest import Browser
    mk_title(db, "Local Gem")
    upstream.fail_tmdb = True
    r = Browser().get("/catalog?section=popular&type=movie")
    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is True and "unavailable" in body["message"]
    assert [i["name"] for i in body["items"]] == ["Local Gem"]  # local fallback


def test_stale_cache_served_when_provider_fails(upstream, monkeypatch):
    from app.cache import cache
    from conftest import Browser
    b = Browser()
    assert b.get("/catalog?section=popular&type=movie").json()["items"]
    for e in list(cache._mem.values()):  # age every entry past its TTL (but within the stale grace window)
        e.fresh_until = 0
    upstream.fail_tmdb = True
    r = b.get("/catalog?section=popular&type=movie").json()
    assert r["items"] and not r["degraded"]  # stale data, no error surfaced


def test_unconfigured_provider_message(db, monkeypatch):
    from app.providers.registry import Registry, set_registry
    from conftest import Browser
    set_registry(Registry())
    r = Browser().get("/catalog?section=popular").json()
    assert r["degraded"] and "TMDB_READ_TOKEN" in r["message"]


def test_retries_then_succeeds(upstream):
    from conftest import Browser
    state = {"n": 0}
    orig = upstream.tmdb

    def flaky(req):
        if not req.url.path.startswith("/3/genre") and state["n"] == 0:
            state["n"] += 1
            import httpx
            return httpx.Response(503)
        return orig(req)

    from app.providers.registry import get_registry
    get_registry().primary_metadata.http._client._transport.handler = flaky
    assert Browser().get("/catalog?section=popular&type=movie").json()["items"]


def test_circuit_breaker_opens_after_repeated_failures(upstream):
    from app.providers.base import _breaker
    from conftest import Browser
    upstream.fail_tmdb = True
    b = Browser()
    for i in range(6):
        b.get(f"/catalog?section=popular&type=movie&page={i + 1}")
    assert _breaker["tmdb"][0] >= 5 and _breaker["tmdb"][1] > 0


def test_kids_profile_only_sees_kids_titles(make_user, upstream):
    u = make_user()
    u.profile = u.post("/profiles", json={"name": "Kiddo", "is_kids": True}).json()["id"]
    items = u.get("/catalog?section=popular&type=movie").json()["items"]
    assert items and all(i["is_kids_safe"] for i in items)


def test_title_detail_syncs_once(upstream, db):
    from conftest import Browser
    b = Browser()
    tid = b.get("/catalog?section=popular&type=movie").json()["items"][0]["id"]
    d = b.get(f"/titles/{tid}").json()
    assert d["runtime_minutes"] == 101 and d["cast"][0]["name"] == "A. Star" and d["external_ids"]["imdb"] == "tt0001"
    assert "TMDB" in " ".join(d["attribution"])
    calls = upstream.count("tmdb/movie/1")
    b.get(f"/titles/{tid}")
    assert upstream.count("tmdb/movie/1") == calls  # details cached in DB/cache


def test_series_seasons_and_episodes(upstream):
    from conftest import Browser
    b = Browser()
    series = b.get("/catalog?section=popular&type=series").json()["items"][0]
    d = b.get(f"/titles/{series['id']}").json()
    assert d["seasons"][0]["number"] == 1
    eps = b.get(f"/titles/{series['id']}/episodes?season=1").json()
    assert [e["name"] for e in eps] == ["Pilot", "Two"] and not any(e["playable"] for e in eps)
    assert b.get(f"/titles/{series['id']}/episodes?season=9").status_code == 404


def test_availability_watchmode_regional_and_labels(upstream):
    from conftest import Browser
    b = Browser()
    tid = b.get("/catalog?section=popular&type=movie").json()["items"][0]["id"]
    a = b.get(f"/titles/{tid}/availability?country=US").json()
    kinds = {(o["provider"], o["kind"]): o for o in a["external"]}
    assert ("Netflix", "subscription") in kinds and kinds[("Netflix", "subscription")]["label"] == "Subscription"
    assert kinds[("Apple", "rent")]["price"] == 2.99  # cheapest format kept
    assert not any(o["provider"] == "Elsewhere" for o in a["external"])  # other region filtered
    assert a["direct"] is None and "Watchmode" in a["attribution"][0]
    n = upstream.count("wm")
    b.get(f"/titles/{tid}/availability?country=US")
    assert upstream.count("wm") == n  # cached in DB for the TTL


def test_availability_falls_back_to_tmdb_when_watchmode_fails(upstream):
    from conftest import Browser
    upstream.fail_watchmode = True
    b = Browser()
    tid = b.get("/catalog?section=popular&type=movie").json()["items"][0]["id"]
    a = b.get(f"/titles/{tid}/availability?country=US").json()
    assert [o["provider"] for o in a["external"]] == ["StreamCo"] and "JustWatch" in a["attribution"][0]


def test_availability_all_providers_down_is_not_an_error(upstream):
    from conftest import Browser
    b = Browser()
    tid = b.get("/catalog?section=popular&type=movie").json()["items"][0]["id"]
    upstream.fail_watchmode = upstream.fail_tmdb = True
    r = b.get(f"/titles/{tid}/availability?country=GB")
    assert r.status_code == 200 and r.json()["degraded"] is True and r.json()["external"] == []


def test_home_aggregates_rows_and_is_cached(upstream):
    from conftest import Browser
    b = Browser()
    h = b.get("/catalog/home").json()
    assert {"trending", "popular_movies", "popular_series"} <= {r["id"] for r in h["rows"]}
    n = len(upstream.calls)
    b.get("/catalog/home")
    assert len(upstream.calls) == n


def test_free_row_only_lists_truly_playable_titles(upstream, db):
    from conftest import Browser
    from helpers import mk_asset, mk_right
    ok, no_rights, unverified = mk_title(db, "Free One"), mk_title(db, "No Rights"), mk_title(db, "Unverified")
    for t in (ok, no_rights, unverified):
        mk_asset(db, t)
    mk_right(db, ok)
    mk_right(db, unverified, status="unverified")
    items = Browser().get("/catalog?section=free").json()["items"]
    assert [i["name"] for i in items] == ["Free One"] and items[0]["direct"]["label"] == "Free to watch here"


def test_languages_and_genres(upstream):
    from conftest import Browser
    b = Browser()
    assert {"code": "te", "name": "తెలుగు", "english_name": "Telugu"} in b.get("/catalog/languages").json()
    assert "Documentary" in b.get("/catalog/genres").json()


def test_invalid_params_rejected(upstream):
    from conftest import Browser
    b = Browser()
    assert b.get("/catalog?section=nope").status_code == 422
    assert b.get("/catalog?page=0").status_code == 422
    assert b.get("/catalog?lang=english").status_code == 422


def test_trending_endpoint_matches_trending_section(upstream):
    from conftest import Browser
    b = Browser()
    r = b.get("/catalog/trending?type=movie")
    assert r.status_code == 200, r.text
    assert [i["name"] for i in r.json()["items"]] == [i["name"] for i in b.get("/catalog?section=trending&type=movie").json()["items"]]


# ---------------------------------------------------------------- country / availability filters, trailers
def test_origin_country_and_availability_filters_reach_provider(upstream):
    from conftest import Browser
    b = Browser()
    r = b.get("/catalog?section=popular&type=movie&origin_country=kr&availability=subscription&watch_region=in")
    assert r.status_code == 200, r.text
    sent = upstream.params["/discover/movie"]
    assert sent["with_origin_country"] == "KR"
    assert sent["watch_region"] == "IN" and sent["with_watch_monetization_types"] == "flatrate"


def test_free_availability_maps_to_free_and_ads(upstream):
    from conftest import Browser
    Browser().get("/catalog?type=movie&availability=free&watch_region=US")
    assert upstream.params["/discover/movie"]["with_watch_monetization_types"] == "free|ads"


def test_filter_values_are_validated(upstream):
    from conftest import Browser
    b = Browser()
    assert b.get("/catalog?availability=stolen").status_code == 422
    assert b.get("/catalog?origin_country=KOR").status_code == 422
    assert b.get("/catalog/search?availability=piracy").status_code == 422


def test_search_with_text_explains_that_country_filters_do_not_apply(upstream):
    from conftest import Browser
    r = Browser().get("/catalog/search?q=alpha&origin_country=US").json()
    assert "not applied" in r["message"] and not r["degraded"]
    assert [i["name"] for i in r["items"]] == ["Alpha Quest"]


def test_search_without_text_applies_country_filter(upstream):
    from conftest import Browser
    Browser().get("/catalog/search?origin_country=JP&type=movie")
    assert upstream.params["/discover/movie"]["with_origin_country"] == "JP"


def _movie_id(db):
    from app.models import TitleExternalId
    return db.query(TitleExternalId).filter_by(provider="tmdb", external_id="1").one().title_id


def test_trailer_prefers_official_trailer_and_embeds_youtube(upstream, db):
    from conftest import Browser
    b = Browser()
    b.get("/catalog?section=popular&type=movie")
    upstream.videos = [
        {"site": "YouTube", "key": "teaserKey01", "type": "Teaser", "official": True, "iso_639_1": "en"},
        {"site": "Vimeo", "key": "vimeoKey001", "type": "Trailer", "official": True},
        {"site": "YouTube", "key": "fanTrailer1", "type": "Trailer", "official": False, "iso_639_1": "en"},
        {"site": "YouTube", "key": "officialTr1", "type": "Trailer", "official": True, "iso_639_1": "en", "name": "Official Trailer"},
    ]
    t = b.get(f"/titles/{_movie_id(db)}/trailer").json()
    assert t["key"] == "officialTr1" and t["embed_url"] == "https://www.youtube-nocookie.com/embed/officialTr1"


def test_trailer_rejects_malformed_key_and_handles_none(upstream, db):
    from conftest import Browser
    b = Browser()
    b.get("/catalog?section=popular&type=movie")
    tid = _movie_id(db)
    upstream.videos = []
    assert b.get(f"/titles/{tid}/trailer").json() is None
    upstream.videos = [{"site": "YouTube", "key": "x\"><script>", "type": "Trailer", "official": True}]
    assert b.get(f"/titles/{tid}/trailer").json() is None  # never reflect an unvalidated key into an iframe URL
    upstream.fail_tmdb = True
    assert b.get(f"/titles/{tid}/trailer").json() is None  # provider outage degrades quietly


# ---------------------------------------------------------------- same name + year must not merge distinct films
def test_distinct_provider_ids_with_same_name_and_year_stay_separate(db):
    from datetime import date

    from app.providers.base import NormalizedTitle
    from app.services.catalog import upsert_titles

    def beast(ext, lang):
        return NormalizedTitle(provider="tmdb", external_id=ext, type="movie", name="Beast",
                               release_date=date(2022, 8, 11), original_language=lang)

    first = upsert_titles(db, [beast("760741", "en")])
    second = upsert_titles(db, [beast("800383", "ko"), beast("828751", "hi")])  # incl. two in one batch
    ids = {first[0][0].id, second[0][0].id, second[1][0].id}
    assert len(ids) == 3
    for t, nt in first + second:
        assert [(e.provider, e.external_id) for e in t.external_ids] == [("tmdb", nt.external_id)]
    # the same TMDB id still resolves to the same title (idempotent)
    again = upsert_titles(db, [beast("800383", "ko")])
    assert again[0][0].id == second[0][0].id


def test_other_provider_may_still_merge_by_name_and_year(db):
    from datetime import date

    from app.providers.base import NormalizedTitle
    from app.services.catalog import upsert_titles

    arch = NormalizedTitle(provider="archive", external_id="beast_1951", type="movie", name="Beast",
                           release_date=date(1951, 1, 1))
    tm = NormalizedTitle(provider="tmdb", external_id="999", type="movie", name="Beast", release_date=date(1951, 5, 1))
    a = upsert_titles(db, [arch])[0][0]
    b = upsert_titles(db, [tm])[0][0]
    assert a.id == b.id and {e.provider for e in b.external_ids} == {"archive", "tmdb"}


def test_trailer_avoids_regional_variants_and_prefers_earliest(upstream, db):
    from conftest import Browser
    b = Browser()
    b.get("/catalog?section=popular&type=movie")
    upstream.videos = [
        {"site": "YouTube", "key": "bwAussie001", "type": "Trailer", "official": True, "iso_639_1": "en",
         "name": "B&W Version Official Australian Trailer", "published_at": "2019-01-01T00:00:00.000Z"},
        {"site": "YouTube", "key": "lateMain001", "type": "Trailer", "official": True, "iso_639_1": "en",
         "name": "Official Trailer", "published_at": "2019-09-01T00:00:00.000Z"},
        {"site": "YouTube", "key": "earlyMain01", "type": "Trailer", "official": True, "iso_639_1": "en",
         "name": "Official Trailer", "published_at": "2019-05-01T00:00:00.000Z"},
    ]
    assert b.get(f"/titles/{_movie_id(db)}/trailer").json()["key"] == "earlyMain01"


def test_season_trailer_and_videos(upstream, db):
    from conftest import Browser
    b = Browser()
    b.get("/catalog?section=popular&type=series")
    from app.models import Title
    series = db.query(Title).filter_by(type="series").first()
    upstream.videos = [
        {"site": "YouTube", "key": "seasonTrailer1", "type": "Trailer", "official": True, "iso_639_1": "en", "name": "Season 1 Trailer"}
    ]
    t = b.get(f"/titles/{series.id}/trailer?season_number=1").json()
    assert t["key"] == "seasonTrailer1"
    vids = b.get(f"/titles/{series.id}/seasons/1/videos").json()
    assert len(vids) == 1
    assert vids[0]["key"] == "seasonTrailer1"


def test_top10_ranks_by_distinct_profiles_and_fills_with_trending(make_user, db):
    from datetime import datetime, timedelta, timezone
    from app.models import PlaybackSession, Profile
    from helpers import mk_title
    u, v = make_user("a@example.com"), make_user("b@example.com")
    hit, other, old = mk_title(db, "Hit"), mk_title(db, "Other"), mk_title(db, "Old")
    import uuid
    pa = db.get(Profile, uuid.UUID(u.profile))
    pb = db.get(Profile, uuid.UUID(v.profile))
    now = datetime.now(timezone.utc)

    def play(title, prof, days_ago=0, country="IN"):
        db.add(PlaybackSession(user_id=prof.user_id, profile_id=prof.id, title_id=title.id, country=country,
                               issued_at=now - timedelta(days=days_ago), expires_at=now + timedelta(hours=1)))

    for _ in range(5):
        play(other, pa)          # one profile replaying does not outrank two different viewers
    play(hit, pa), play(hit, pb)
    play(old, pa, days_ago=30)   # outside the week
    db.commit()
    from app.services.catalog import top_played
    assert [c.name for c in top_played(db, "IN", False)] == ["Hit", "Other"]
    assert [c.name for c in top_played(db, "US", False)] == []          # other country: no plays
    kid = mk_title(db, "Kid film", kids=True)
    play(kid, pa)
    db.commit()
    assert "Other" not in [c.name for c in top_played(db, "IN", True)]  # kids profile only sees family-safe titles


def test_top10_row_hidden_until_enough_titles_were_played():
    from app.services.catalog import TOP_MIN_PLAYED, top10_items
    card = lambda i: {"id": str(i), "name": f"T{i}"}
    trending = [card(100 + i) for i in range(12)]
    assert top10_items([card(i) for i in range(TOP_MIN_PLAYED - 1)], trending) == []   # too few plays: Trending only
    row = top10_items([card(i) for i in range(TOP_MIN_PLAYED)], trending)
    assert len(row) == 10 and [c["id"] for c in row[:TOP_MIN_PLAYED]] == [str(i) for i in range(TOP_MIN_PLAYED)]
    assert top10_items([card(0)] * 5, [card(0), card(1)])[-1]["id"] == "1"             # no duplicates from the top-up
