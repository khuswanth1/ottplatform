from typing import Annotated, Literal
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import clean_country, get_optional_profile, get_optional_user, resolve_country
from ..maturity import blocked
from ..models import Episode, MediaAsset, Profile, Season, Title, TitleGenre, TitleMarker, User
from ..ratelimit import rate_limit
from ..maturity import profile_level
from ..schemas import AvailabilityOut, EpisodeOut, MarkerOut, TitleCard, TitleDetail
from ..services import availability as avail
from ..providers.base import ProviderError
from ..providers.registry import get_registry
from ..services import catalog as svc

router = APIRouter(prefix="/titles", tags=["titles"])


def get_visible_title(db: Session, title_id: uuid.UUID, profile: Profile | None) -> Title:
    t = svc.load_title_full(db, title_id)
    if not t or t.status != "published" or blocked(profile, t):
        raise HTTPException(404, "Title not found.")
    return t


@router.get("/{title_id}", response_model=TitleDetail, dependencies=[Depends(rate_limit("title", 120, 60))])
def get_title(title_id: uuid.UUID, request: Request, profile: Profile | None = Depends(get_optional_profile),
              db: Session = Depends(get_db)):
    t = get_visible_title(db, title_id, profile)
    svc.ensure_details(db, t, profile.language if profile else "en")  # failure => serve cached data
    t = get_visible_title(db, title_id, profile)  # re-check kids rating after a detail sync
    return svc.to_detail(db, t, resolve_country(request))


@router.get("/{title_id}/markers", response_model=list[MarkerOut])
def markers(title_id: uuid.UUID, episode_id: uuid.UUID | None = None, profile: Profile | None = Depends(get_optional_profile),
            db: Session = Depends(get_db)):
    """Skip-intro, skip-recap and credits ranges for a film, or for one episode of a series."""
    t = get_visible_title(db, title_id, profile)
    key = str(episode_id) if episode_id else "-"
    if t.type == "series" and not episode_id:
        return []
    return db.scalars(select(TitleMarker).where(TitleMarker.title_id == t.id, TitleMarker.episode_key == key)
                      .order_by(TitleMarker.start_s)).all()


SIMILAR_LIMIT = 12


@router.get("/{title_id}/similar", response_model=list[TitleCard], dependencies=[Depends(rate_limit("similar", 60, 60))])
def similar(title_id: uuid.UUID, request: Request, profile: Profile | None = Depends(get_optional_profile),
            db: Session = Depends(get_db)):
    """Published titles of the same type that share genres with this one, most shared genres first, then most popular.
    Computed from the local catalog (no provider calls), so it is only as good as what has been synced."""
    t = get_visible_title(db, title_id, profile)
    gids = [g.id for g in t.genres]
    if not gids:
        return []
    shared = func.count(TitleGenre.genre_id).label("shared")
    stmt = (select(Title, shared).join(TitleGenre, TitleGenre.title_id == Title.id)
            .where(TitleGenre.genre_id.in_(gids), Title.id != t.id, Title.type == t.type, Title.status == "published"))
    if profile and profile.is_kids:
        stmt = stmt.where(Title.is_kids_safe.is_(True))
    rows = db.execute(stmt.group_by(Title.id).order_by(shared.desc(), Title.popularity.desc().nullslast(), Title.id)
                      .limit(SIMILAR_LIMIT * 3)).unique().all()
    picked = [r[0] for r in rows if not blocked(profile, r[0])][:SIMILAR_LIMIT]
    return svc.cards_from_titles(db, picked, resolve_country(request), bool(profile and profile.is_kids), profile_level(profile))


_YT_KEY = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


@router.get("/{title_id}/trailer", dependencies=[Depends(rate_limit("trailer", 60, 60))])
def trailer(title_id: uuid.UUID, season_number: int | None = Query(None),
            profile: Profile | None = Depends(get_optional_profile), db: Session = Depends(get_db)):
    """Official trailer from the metadata provider (YouTube embed), or null. Trailers are promotional material the
    studio publishes for embedding; this is not the title's playable stream."""
    t = get_visible_title(db, title_id, profile)
    tmdb_id = svc.title_ext(t).get("tmdb")
    prov = get_registry().primary_metadata
    if not tmdb_id or prov is None:
        return None
    try:
        v = prov.trailer(t.type, tmdb_id, profile.language if profile else "en", season_number=season_number)
    except TypeError:
        v = prov.trailer(t.type, tmdb_id, profile.language if profile else "en")
    except ProviderError:
        return None
    if not v or v.get("site") != "YouTube" or not _YT_KEY.match(v.get("key", "")):
        return None
    return {**v, "embed_url": f"https://www.youtube-nocookie.com/embed/{v['key']}"}


@router.get("/{title_id}/seasons/{season_number}/videos", dependencies=[Depends(rate_limit("trailer", 60, 60))])
def season_videos(title_id: uuid.UUID, season_number: int,
                  profile: Profile | None = Depends(get_optional_profile), db: Session = Depends(get_db)):
    """Fetch all season-specific videos (trailers, teasers, featurettes, recaps) from TMDB."""
    t = get_visible_title(db, title_id, profile)
    if t.type != "series":
        raise HTTPException(400, "Only series have seasons.")
    tmdb_id = svc.title_ext(t).get("tmdb")
    prov = get_registry().primary_metadata
    if not tmdb_id or prov is None:
        return []
    try:
        if hasattr(prov, "season_videos"):
            return prov.season_videos(tmdb_id, season_number, profile.language if profile else "en-US")
    except ProviderError:
        return []
    return []


@router.get("/{title_id}/availability", response_model=AvailabilityOut,
            dependencies=[Depends(rate_limit("availability", 60, 60))])
def availability(title_id: uuid.UUID, request: Request, country: str | None = Query(default=None, max_length=2),
                 user: User | None = Depends(get_optional_user), profile: Profile | None = Depends(get_optional_profile),
                 db: Session = Depends(get_db)):
    t = get_visible_title(db, title_id, profile)
    viewer = resolve_country(request)
    cc = clean_country(country, viewer)
    return avail.build_availability(db, t, cc, user.plan if user else "free", bool(user and user.role == "admin"),
                                    rights_country=viewer)


@router.get("/{title_id}/episodes", response_model=list[EpisodeOut])
def episodes(title_id: uuid.UUID, request: Request, season: int = Query(default=1, ge=0, le=200),
             profile: Profile | None = Depends(get_optional_profile), db: Session = Depends(get_db)):
    t = get_visible_title(db, title_id, profile)
    if t.type != "series":
        raise HTTPException(400, "This title has no episodes.")
    s = db.scalar(select(Season).where(Season.title_id == t.id, Season.number == season))
    if not s:
        svc.ensure_details(db, t)
        s = db.scalar(select(Season).where(Season.title_id == t.id, Season.number == season))
    if not s:
        raise HTTPException(404, "Season not found.")
    svc.ensure_episodes(db, t, s, profile.language if profile else "en")
    eps = db.scalars(select(Episode).where(Episode.season_id == s.id).order_by(Episode.number)).all()
    title_ok = t.id in svc.direct_access(db, [t.id], resolve_country(request))
    with_assets = set(db.scalars(select(MediaAsset.episode_id).where(
        MediaAsset.title_id == t.id, MediaAsset.is_active.is_(True), MediaAsset.episode_id.is_not(None))))
    return [EpisodeOut(id=e.id, season=s.number, number=e.number, name=e.name, overview=e.overview, air_date=e.air_date,
                       runtime_minutes=e.runtime_minutes, still_url=svc.image_url(e.still_path, "still"),
                       playable=title_ok and e.id in with_assets) for e in eps]


@router.get("/{title_id}/seasons/{season_number}/watch-providers", dependencies=[Depends(rate_limit("availability", 60, 60))])
def season_watch_providers(title_id: uuid.UUID, season_number: int,
                           profile: Profile | None = Depends(get_optional_profile), db: Session = Depends(get_db)):
    """Fetch authorized watch providers for a TV series season from TMDB."""
    t = get_visible_title(db, title_id, profile)
    if t.type != "series":
        raise HTTPException(400, "Only series have seasons.")
    tmdb_id = svc.title_ext(t).get("tmdb")
    prov = get_registry().primary_metadata
    if not tmdb_id or prov is None or not hasattr(prov, "season_watch_providers"):
        return {}
    try:
        return prov.season_watch_providers(tmdb_id, season_number, profile.language if profile else "en-US")
    except ProviderError:
        return {}


@router.get("/collection/{collection_id}/translations", dependencies=[Depends(rate_limit("title", 60, 60))])
def collection_translations(collection_id: Annotated[str, Path(pattern=r"^\d{1,10}$")]):
    """Fetch collection translations from TMDB."""
    prov = get_registry().primary_metadata
    if not prov or not hasattr(prov, "collection_translations"):
        return []
    try:
        return prov.collection_translations(collection_id)
    except ProviderError:
        return []


@router.get("/guest-session/{guest_session_id}/rated/{kind:path}", dependencies=[Depends(rate_limit("title", 60, 60))])
def guest_session_rated(guest_session_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_]{1,64}$")], kind: Literal["movies", "tv", "tv/episodes"] = "movies",
                        page: int = Query(1, ge=1, le=500), sort_by: str = "created_at.asc",
                        profile: Profile | None = Depends(get_optional_profile)):
    """Fetch rated titles for a TMDB guest session."""
    prov = get_registry().primary_metadata
    if not prov or not hasattr(prov, "guest_session_rated"):
        return {}
    try:
        return prov.guest_session_rated(guest_session_id, kind=kind, page=page, sort_by=sort_by,
                                        language=profile.language if profile else "en-US")
    except ProviderError:
        return {}

