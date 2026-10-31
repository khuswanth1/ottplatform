import os
import re

os.environ["ENV_FILE"] = "none.env"  # tests never read a developer's real .env
os.environ["REDIS_URL"] = ""
os.environ.setdefault("DATABASE_URL", "sqlite://")  # CI also runs the suite against PostgreSQL
os.environ.update({
    "ENV": "test", "TMDB_READ_TOKEN": "test-token", "WATCHMODE_API_KEY": "wm-test",
    "DEFAULT_COUNTRY": "US", "COUNTRY_HEADER": "X-Test-Country", "FRONTEND_URL": "http://localhost:5173",
    "CORS_ORIGINS": "http://localhost:5173", "PROVIDER_RETRIES": "1", "CDN_SIGNING_SECRET": "",
})

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import mailer  # noqa: E402
from app.cache import cache  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.providers import base as pbase  # noqa: E402
from app.providers.archive import ArchiveProvider  # noqa: E402
from app.providers.base import ProviderHTTP  # noqa: E402
from app.providers.registry import Registry, set_registry  # noqa: E402
from app.providers.tmdb import TMDBProvider  # noqa: E402
from app.providers.watchmode import WatchmodeProvider  # noqa: E402
from app.ratelimit import reset_limits  # noqa: E402
from app.security import hash_password  # noqa: E402

GENRES = {"genres": [{"id": 28, "name": "Action"}, {"id": 99, "name": "Documentary"}, {"id": 10751, "name": "Family"},
                     {"id": 16, "name": "Animation"}, {"id": 18, "name": "Drama"}]}


def movie(i, name, year=2020, lang="en", genres=(28,), adult=False):
    return {"id": i, "title": name, "original_title": name, "overview": f"About {name}", "release_date": f"{year}-05-01",
            "poster_path": f"/p{i}.jpg", "backdrop_path": f"/b{i}.jpg", "vote_average": 7.5, "popularity": 100 - i,
            "genre_ids": list(genres), "original_language": lang, "adult": adult}


class Upstream:
    """Scriptable fake of TMDB + Watchmode HTTP APIs (served through httpx.MockTransport -> real adapters run)."""

    def __init__(self):
        self.calls: list[str] = []
        self.fail_tmdb = False
        self.fail_watchmode = False
        self.params: dict[str, dict] = {}  # last query params seen per TMDB path
        self.videos: list[dict] = []
        self.movies = [movie(1, "Alpha Quest"), movie(2, "Beta Run", lang="te"), movie(3, "Kid Fun", genres=(16, 10751)),
                       movie(4, "Gamma Docu", genres=(99,))]

    def tmdb(self, req: httpx.Request) -> httpx.Response:
        p = req.url.path.removeprefix("/3")
        self.calls.append("tmdb" + p)
        self.params[p] = dict(req.url.params)
        if self.fail_tmdb:
            return httpx.Response(500)
        if re.fullmatch(r"/(movie|tv)/\d+(/season/\d+)?/videos", p):
            return httpx.Response(200, json={"results": self.videos})
        if p.startswith("/genre/"):
            return httpx.Response(200, json=GENRES)
        if p.startswith("/search/person"):
            return httpx.Response(200, json={"results": [{"id": 77, "name": "Some Actor"}]})
        if p.startswith("/search/") or "/popular" in p or "/trending" in p or "/top_rated" in p or p.startswith("/discover/"):
            items = self.movies
            q = req.url.params.get("query")
            if q:
                items = [m for m in items if q.lower() in m["title"].lower()]
            if p == "/search/multi":
                items = [{**m, "media_type": "movie"} for m in items]
            lang = req.url.params.get("with_original_language")
            if lang:
                items = [m for m in items if m["original_language"] == lang]
            if p.endswith("/tv") or "/tv/" in p:
                items = [{"id": 900 + m["id"], "name": m["title"], "original_name": m["title"], "overview": m["overview"],
                          "first_air_date": m["release_date"], "poster_path": m["poster_path"],
                          "genre_ids": m["genre_ids"], "original_language": m["original_language"],
                          "popularity": m["popularity"], "vote_average": 8} for m in items[:1]]
            return httpx.Response(200, json={"page": 1, "total_pages": 3, "results": items})
        if re.fullmatch(r"/movie/\d+/watch/providers", p):
            return httpx.Response(200, json={"results": {"US": {"link": "https://justwatch.example/x",
                                                               "flatrate": [{"provider_name": "StreamCo"}]}}})
        if re.fullmatch(r"/movie/\d+", p):
            m = next(x for x in self.movies if x["id"] == int(p.split("/")[-1]))
            return httpx.Response(200, json={**m, "genres": [{"id": g, "name": {28: "Action", 99: "Documentary", 16: "Animation", 10751: "Family"}[g]} for g in m["genre_ids"]],
                                             "runtime": 101, "spoken_languages": [{"iso_639_1": "en"}],
                                             "credits": {"cast": [{"id": 5, "name": "A. Star", "character": "Hero"}]},
                                             "external_ids": {"imdb_id": f"tt000{m['id']}"},
                                             "release_dates": {"results": [{"iso_3166_1": "US", "release_dates": [{"certification": "PG" if 16 in m["genre_ids"] else "R"}]}]}})
        if re.fullmatch(r"/tv/\d+", p):
            return httpx.Response(200, json={"id": 901, "name": "Series One", "original_name": "Series One", "overview": "s",
                                             "first_air_date": "2019-01-01", "genres": [{"id": 18, "name": "Drama"}],
                                             "episode_run_time": [45], "original_language": "en", "poster_path": "/s.jpg",
                                             "seasons": [{"season_number": 1, "name": "Season 1", "episode_count": 2}],
                                             "content_ratings": {"results": [{"iso_3166_1": "US", "rating": "TV-14"}]}})
        if re.fullmatch(r"/tv/\d+/season/\d+", p):
            return httpx.Response(200, json={"episodes": [{"episode_number": 1, "name": "Pilot"}, {"episode_number": 2, "name": "Two"}]})
        if p == "/configuration/languages":
            return httpx.Response(200, json=[{"iso_639_1": "en", "english_name": "English", "name": "English"},
                                             {"iso_639_1": "te", "english_name": "Telugu", "name": "తెలుగు"}])
        return httpx.Response(404)

    def watchmode(self, req: httpx.Request) -> httpx.Response:
        self.calls.append("wm" + req.url.path)
        if self.fail_watchmode:
            return httpx.Response(503)
        if req.url.path.startswith("/v1/search") or req.url.path == "/search/":
            return httpx.Response(200, json={"title_results": [{"id": 555}]})
        return httpx.Response(200, json=[
            {"source_id": 1, "name": "Netflix", "type": "sub", "region": "US", "web_url": "https://netflix.example/t", "format": "HD"},
            {"source_id": 2, "name": "Apple", "type": "rent", "region": "US", "web_url": "https://apple.example/t", "price": 3.99, "format": "HD"},
            {"source_id": 2, "name": "Apple", "type": "rent", "region": "US", "web_url": "https://apple.example/t", "price": 2.99, "format": "SD"},
            {"source_id": 9, "name": "Elsewhere", "type": "sub", "region": "GB", "web_url": "https://x.example"},
        ])

    def count(self, prefix: str) -> int:
        return sum(1 for c in self.calls if c.startswith(prefix))


@pytest.fixture(autouse=True)
def clean_state():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    cache.clear()
    reset_limits()
    pbase.reset_breakers()
    app.state.enforce_limits = False
    yield
    set_registry(None)


@pytest.fixture
def upstream(monkeypatch):
    up = Upstream()
    monkeypatch.setattr("time.sleep", lambda *_: None)  # no real backoff delays in tests
    reg = Registry()
    wm = WatchmodeProvider(ProviderHTTP("watchmode", "https://api.watchmode.com/v1", {}, {"apiKey": "k"},
                                        transport=httpx.MockTransport(up.watchmode)))
    tmdb = TMDBProvider(ProviderHTTP("tmdb", "https://api.themoviedb.org/3", {}, {}, transport=httpx.MockTransport(up.tmdb)))
    reg.register(wm)
    reg.register(tmdb)
    reg.register(ArchiveProvider(ProviderHTTP("archive", "https://archive.org", {}, {}, transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"response": {"docs": [{"identifier": "old_film", "title": "Old Film", "year": "1931"}]}})))))
    set_registry(reg)
    return up


@pytest.fixture
def mails(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send_mail", lambda to, subject, body: sent.append((to, subject, body)))
    monkeypatch.setattr("app.routers.auth.send_mail", lambda to, subject, body: sent.append((to, subject, body)))
    return sent


@pytest.fixture
def db():
    with SessionLocal() as s:
        yield s


class Browser:
    """A client with its own cookie jar plus CSRF/profile header handling."""

    def __init__(self):
        self.c = TestClient(app, base_url="http://localhost")
        self.csrf = ""
        self.profile = ""
        self.country = ""

    def headers(self, extra=None):
        h = {"X-CSRF-Token": self.csrf} if self.csrf else {}
        if self.profile:
            h["X-Profile-Id"] = self.profile
        if self.country:
            h["X-Test-Country"] = self.country
        return {**h, **(extra or {})}

    def request(self, method, url, **kw):
        h = self.headers(kw.pop("headers", None))
        return self.c.request(method, "/api/v1" + url, headers=h, **kw)

    def get(self, url, **kw): return self.request("GET", url, **kw)
    def post(self, url, **kw): return self.request("POST", url, **kw)
    def put(self, url, **kw): return self.request("PUT", url, **kw)
    def patch(self, url, **kw): return self.request("PATCH", url, **kw)
    def delete(self, url, **kw): return self.request("DELETE", url, **kw)


PASSWORD = "correct horse battery"


def signup(mails, email="user@example.com", verify=True, password=PASSWORD) -> Browser:
    b = Browser()
    r = b.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code == 202, r.text
    if verify:
        token = re.search(r"token=([\w-]+)", mails[-1][2]).group(1)
        assert b.post("/auth/verify-email", json={"token": token}).status_code == 200
        r = b.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        b.csrf = r.json()["csrf_token"]
        b.profile = b.get("/profiles").json()[0]["id"]
    return b


@pytest.fixture
def make_user(mails):
    return lambda email="user@example.com", **kw: signup(mails, email, **kw)


@pytest.fixture
def make_admin(mails, db):
    def _make(email="admin@example.com"):
        b = signup(mails, email)
        u = db.query(User).filter_by(email=email).one()
        u.role = "admin"
        db.commit()
        return b
    return _make
