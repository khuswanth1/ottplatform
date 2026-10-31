from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..cache import cache
from ..db import get_db
from ..deps import get_optional_profile, get_profile, require_verified, resolve_country
from ..maturity import blocked, profile_level
from ..models import FeaturedTitle, Genre, Language, Profile, Title, User
from ..providers.base import ProviderError
from ..providers.registry import get_registry
from ..ratelimit import rate_limit
from ..schemas import CatalogPage, TitleCard
from ..services import catalog as svc
from ..services.recommend import recommend

router = APIRouter(prefix="/catalog", tags=["catalog"])

Section = Literal["trending", "trending_today", "popular", "top_rated", "upcoming", "recent", "free"]
ContentType = Literal["movie", "series", "documentary", "all"]
Availability = Literal["free", "subscription", "rent", "buy"]


def _lang(profile: Profile | None, lang: str | None) -> str:
    return lang or (profile.language if profile else "en")


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()] if v else []


@router.get("", response_model=CatalogPage, dependencies=[Depends(rate_limit("catalog", 120, 60))])
def browse(
    request: Request,
    section: Section = "popular",
    type: ContentType = "all",
    lang: str | None = Query(default=None, pattern=r"^[a-z]{2,3}$", description="display language"),
    original_language: str | None = Query(default=None, pattern=r"^[a-z]{2,3}$", description="content language"),
    genre: str | None = Query(default=None, max_length=200, description="comma-separated genre names"),
    year: int | None = Query(default=None, ge=1880, le=2100),
    origin_country: str | None = Query(default=None, pattern=r"^[A-Za-z]{2}$", description="country the title was produced in"),
    availability: Availability | None = Query(default=None, description="how it can be watched in watch_region"),
    watch_region: str | None = Query(default=None, pattern=r"^[A-Za-z]{2}$", description="region for availability (display choice)"),
    page: int = Query(default=1, ge=1, le=500),
    profile: Profile | None = Depends(get_optional_profile),
    db: Session = Depends(get_db),
):
    return svc.section_page(db, section, type, page, _lang(profile, lang), resolve_country(request),
                            bool(profile and profile.is_kids), original_language, _csv(genre), year,
                            origin_country, availability, watch_region, profile_level(profile))


@router.get("/trending", response_model=CatalogPage, dependencies=[Depends(rate_limit("catalog", 120, 60))])
def trending(
    request: Request,
    type: ContentType = "all",
    lang: str | None = Query(default=None, pattern=r"^[a-z]{2,3}$"),
    original_language: str | None = Query(default=None, pattern=r"^[a-z]{2,3}$"),
    page: int = Query(default=1, ge=1, le=500),
    profile: Profile | None = Depends(get_optional_profile),
    db: Session = Depends(get_db),
):
    return svc.section_page(db, "trending", type, page, _lang(profile, lang), resolve_country(request),
                            bool(profile and profile.is_kids), original_language, [], None, level=profile_level(profile))


HOME_ROWS = [
    ("free", "Free to watch here", "free", "all", None),
    ("trending", "Trending this week", "trending", "all", None),
    ("trending_today", "Trending today", "trending_today", "all", None),
    ("popular_movies", "Popular movies", "popular", "movie", None),
    ("popular_series", "Popular series", "popular", "series", None),
    ("regional", None, "popular", "all", "profile_language"),
    ("top_movies", "Top-rated movies", "top_rated", "movie", None),
    ("top_series", "Top-rated series", "top_rated", "series", None),
    ("documentaries", "Documentaries", "popular", "documentary", None),
    ("upcoming", "Coming soon", "upcoming", "movie", None),
    ("recent", "Recently added", "recent", "all", None),
]


@router.get("/home", dependencies=[Depends(rate_limit("home", 60, 60))])
def home(request: Request, lang: str | None = Query(default=None, pattern=r"^[a-z]{2,3}$"),
         profile: Profile | None = Depends(get_optional_profile), db: Session = Depends(get_db)):
    """All home rows in one round trip, cached for 5 minutes per (language, country, kids) combination."""
    language, country = _lang(profile, lang), resolve_country(request)
    kids, level = bool(profile and profile.is_kids), profile_level(profile)
    key = f"home:{language}:{country}:{level}"

    def build():
        rows, any_degraded = [], False
        names = {}
        try:
            names = {l.code: l.english_name or l.name for l in db.scalars(select(Language).where(Language.code == language))}
        except Exception:
            pass
        for rid, title, section, typ, special in HOME_ROWS:
            orig = language if special == "profile_language" else None
            if special == "profile_language":
                if language == "en":
                    continue
                title = f"Popular in {names.get(language, language.upper())}"
            page = svc.section_page(db, section, typ, 1, language, country, kids, orig, level=level)
            any_degraded |= page.degraded
            if page.items:
                rows.append({"id": rid, "title": title, "items": [i.model_dump(mode="json") for i in page.items[:20]]})
        played = [c.model_dump(mode="json") for c in svc.top_played(db, country, kids, level)]
        fill = next((r["items"] for r in rows if r["id"] == "trending"), [])  # top up a short list with trending
        if top := svc.top10_items(played, fill):
            rows.insert(0, {"id": "top10", "title": "Top 10 this week", "ranked": True, "items": top})
        return {"rows": rows, "degraded": any_degraded,
                "attribution": [p.attribution for p in get_registry().metadata if p.configured() and p.attribution],
                "providers": get_registry().status()}

    data, _ = cache.get_or_load(key, 300, build)
    return data


@router.get("/recommended", response_model=list[TitleCard], dependencies=[Depends(rate_limit("recommended", 60, 60))])
def recommended(request: Request, _: User = Depends(require_verified), profile: Profile = Depends(get_profile),
                db: Session = Depends(get_db)):
    """Picks for this profile from its own history, ratings and lists. Empty until the profile has done something.
    Not part of /home because that response is cached for everyone in a country."""
    return recommend(db, profile, resolve_country(request))


@router.get("/search", response_model=CatalogPage, dependencies=[Depends(rate_limit("search", 60, 60))])
def search(
    request: Request,
    q: str | None = Query(default=None, min_length=1, max_length=100),
    actor: str | None = Query(default=None, min_length=1, max_length=100),
    genre: str | None = Query(default=None, max_length=200),
    lang: str | None = Query(default=None, pattern=r"^[a-z]{2,3}$"),
    original_language: str | None = Query(default=None, pattern=r"^[a-z]{2,3}$"),
    year: int | None = Query(default=None, ge=1880, le=2100),
    type: Literal["movie", "series", "documentary"] | None = None,
    origin_country: str | None = Query(default=None, pattern=r"^[A-Za-z]{2}$"),
    availability: Availability | None = None,
    watch_region: str | None = Query(default=None, pattern=r"^[A-Za-z]{2}$"),
    page: int = Query(default=1, ge=1, le=500),
    profile: Profile | None = Depends(get_optional_profile),
    db: Session = Depends(get_db),
):
    return svc.search_page(
        db, q=q, actor=actor, genres=_csv(genre), language=_lang(profile, lang), original_language=original_language,
        year=year, type_=type, page=page, country=resolve_country(request), kids=bool(profile and profile.is_kids),
        origin_country=origin_country, availability=availability, watch_region=watch_region,
        level=profile_level(profile),
    )


@router.get("/suggest", dependencies=[Depends(rate_limit("suggest", 120, 60))])
def suggest(q: str = Query(min_length=2, max_length=100), profile: Profile | None = Depends(get_optional_profile),
            db: Session = Depends(get_db)):
    """Typeahead: up to 8 published titles whose name starts with what was typed (punctuation and case ignored)."""
    n = svc.norm_name(q)
    if len(n) < 2:
        return []
    # norm_name keeps only letters, digits and marks, so n holds no LIKE wildcards
    stmt = select(Title).where(Title.status == "published", Title.norm_name.like(n + "%"))
    if profile and profile.is_kids:
        stmt = stmt.where(Title.is_kids_safe.is_(True))
    rows = db.scalars(stmt.order_by(Title.popularity.desc().nullslast(), Title.id).limit(24)).unique().all()
    return [{"id": str(t.id), "name": t.name, "year": t.year, "type": t.type} for t in rows if not blocked(profile, t)][:8]


@router.get("/genres")
def genres(lang: str = Query(default="en", pattern=r"^[a-z]{2,3}$"), db: Session = Depends(get_db)):
    prov = get_registry().primary_metadata
    if prov:
        try:
            return sorted(prov.genres(lang))
        except ProviderError:
            pass
    return [g.name for g in db.scalars(select(Genre).order_by(Genre.name))]


@router.get("/languages")
def languages(db: Session = Depends(get_db)):
    prov = get_registry().primary_metadata
    if prov:
        try:
            data, _ = cache.get_or_load("languages", 7 * 86400, prov.languages)
            return sorted((x for x in data if x["code"] != "xx"), key=lambda x: x["english_name"])
        except ProviderError:
            pass
    return [{"code": l.code, "name": l.name, "english_name": l.english_name} for l in db.scalars(select(Language))]


@router.get("/featured", response_model=list[TitleCard], dependencies=[Depends(rate_limit("catalog", 120, 60))])
def featured(request: Request, profile: Profile | None = Depends(get_optional_profile), db: Session = Depends(get_db)):
    """Curated billboard titles for the viewer's trusted country (or worldwide), inside their date window.
    Empty list means nothing is curated; the client then falls back to a trending title."""
    country, kids, ts = resolve_country(request), bool(profile and profile.is_kids), datetime.now(timezone.utc)
    rows = db.execute(
        select(FeaturedTitle, Title).join(Title, Title.id == FeaturedTitle.title_id)
        .where(FeaturedTitle.country.in_(["*", country]),
               or_(FeaturedTitle.starts_at.is_(None), FeaturedTitle.starts_at <= ts),
               or_(FeaturedTitle.ends_at.is_(None), FeaturedTitle.ends_at > ts))
        .order_by(FeaturedTitle.position, FeaturedTitle.created_at).limit(10)).all()
    seen, titles = set(), []
    for _, t in rows:  # a title curated both worldwide and for this country appears once
        if t.id not in seen:
            seen.add(t.id)
            titles.append(t)
    return svc.cards_from_titles(db, titles, country, kids, profile_level(profile))


@router.get("/keyword/{keyword_id}", response_model=CatalogPage, dependencies=[Depends(rate_limit("catalog", 120, 60))])
def keyword_movies(keyword_id: Annotated[str, Path(pattern=r"^\d{1,10}$")], request: Request, page: int = Query(1, ge=1, le=500),
                   lang: str | None = Query(None, pattern=r"^[a-z]{2,3}$"),
                   profile: Profile | None = Depends(get_optional_profile), db: Session = Depends(get_db)):
    """Fetch movies associated with a specific TMDB keyword."""
    prov = get_registry().primary_metadata
    language, country = _lang(profile, lang), resolve_country(request)
    kids, level = bool(profile and profile.is_kids), profile_level(profile)
    if not prov or not hasattr(prov, "keyword_movies"):
        return CatalogPage(items=[], page=page, total_pages=1, degraded=True)
    try:
        p = prov.keyword_movies(keyword_id, page=page, language=language)
        pairs = svc.upsert_titles(db, p.items)
        cards = svc.cards_from_pairs(db, pairs, country, kids, level)
        return CatalogPage(items=cards, page=p.page, total_pages=p.total_pages, degraded=p.stale)
    except ProviderError:
        return CatalogPage(items=[], page=page, total_pages=1, degraded=True)


@router.get("/person/{person_id}/credits", dependencies=[Depends(rate_limit("catalog", 120, 60))])
def person_credits(person_id: Annotated[str, Path(pattern=r"^\d{1,10}$")], type: Literal["movie", "series"] = "movie",
                   lang: str | None = Query(None, pattern=r"^[a-z]{2,3}$"),
                   profile: Profile | None = Depends(get_optional_profile)):
    """Fetch all movie or TV credits for a person from TMDB."""
    prov = get_registry().primary_metadata
    language = _lang(profile, lang)
    if not prov or not hasattr(prov, "person_credits"):
        return {}
    try:
        return prov.person_credits(person_id, type_=type, language=language)
    except ProviderError:
        return {}


@router.get("/person/{person_id}/translations", dependencies=[Depends(rate_limit("catalog", 120, 60))])
def person_translations(person_id: Annotated[str, Path(pattern=r"^\d{1,10}$")]):
    """Fetch translations for a person biography and details from TMDB."""
    prov = get_registry().primary_metadata
    if not prov or not hasattr(prov, "person_translations"):
        return []
    try:
        return prov.person_translations(person_id)
    except ProviderError:
        return []


@router.get("/providers/{content_type}", dependencies=[Depends(rate_limit("catalog", 120, 60))])
def watch_providers_list(content_type: Literal["movie", "tv"] = "movie",
                         lang: str | None = Query(None, pattern=r"^[a-z]{2,3}$"),
                         watch_region: str | None = Query(None, pattern=r"^[A-Za-z]{2}$"),
                         profile: Profile | None = Depends(get_optional_profile)):
    """List authorized streaming watch providers available on TMDB for movies or TV shows."""
    prov = get_registry().primary_metadata
    language = _lang(profile, lang)
    if not prov or not hasattr(prov, "watch_providers_list"):
        return []
    try:
        return prov.watch_providers_list(type_=content_type, language=language, watch_region=watch_region)
    except ProviderError:
        return []

