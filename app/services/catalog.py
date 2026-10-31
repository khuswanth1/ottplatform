"""Unified catalog: normalizes provider results, de-duplicates them into one `titles` table, and serves cards."""
import re
import unicodedata
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from ..config import get_settings
from ..maturity import title_allowed
from ..models import (
    CastMember, CrewMember, Episode, Genre, Language, MediaAsset, PlaybackSession, Season, Title, TitleExternalId, TitleGenre, TitleRight,
)
from ..providers.base import NormalizedTitle, Page, ProviderError
from ..providers.registry import get_registry
from ..schemas import CastOut, CatalogPage, CrewOut, DirectAccess, SeasonOut, TitleCard, TitleDetail

KIDS_OK = {"G", "PG", "TV-Y", "TV-Y7", "TV-G", "TV-PG", "U", "UC", "0", "6"}
KIDS_GENRES = {"Family", "Kids", "Animation"}
TMDB_IMAGE = {"poster": "w342", "backdrop": "w1280", "profile": "w185", "still": "w300"}


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    # keep letters, digits and combining marks (needed for Indic scripts); drop punctuation/space
    return "".join(c for c in s if unicodedata.category(c)[0] in "LNM")[:300]


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "genre"


def image_url(path: str | None, kind: str = "poster") -> str | None:
    if not path:
        return None
    if path.startswith("http"):
        return path
    return f"{get_settings().tmdb_image_base}{TMDB_IMAGE[kind]}{path}"


def kids_safe(nt: NormalizedTitle) -> bool:
    if nt.adult:
        return False
    if nt.age_rating:
        return nt.age_rating.upper() in KIDS_OK
    return bool(KIDS_GENRES & set(nt.genres)) and "Horror" not in nt.genres


# ------------------------------------------------------------------ reference data
def _insert_ignore(db: Session, model, rows: list[dict]) -> None:
    """INSERT ... ON CONFLICT DO NOTHING so concurrent requests can't fail on shared reference rows."""
    if not rows:
        return
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(insert(model).values(rows).on_conflict_do_nothing())


def ensure_languages(db: Session, codes: set[str]) -> None:
    codes = {c for c in codes if c}
    if not codes:
        return
    have = set(db.scalars(select(Language.code).where(Language.code.in_(codes))))
    _insert_ignore(db, Language, [{"code": c, "name": c, "english_name": c} for c in codes - have])


def ensure_genres(db: Session, names: set[str]) -> dict[str, Genre]:
    names = {n for n in names if n}
    if not names:
        return {}
    out = {g.name: g for g in db.scalars(select(Genre).where(Genre.name.in_(names)))}
    missing = names - out.keys()
    if missing:
        _insert_ignore(db, Genre, [{"name": n, "slug": slugify(n)} for n in missing])
        for g in db.scalars(select(Genre).where(Genre.name.in_(missing))):
            out[g.name] = g
    return out


# ------------------------------------------------------------------ upsert / dedupe
def _apply_listing_fields(t: Title, nt: NormalizedTitle) -> None:
    if t.source == "admin":  # manually curated titles are never overwritten by providers
        return
    t.name = nt.name or t.name
    t.norm_name = norm_name(t.name)
    t.original_name = nt.original_name or t.original_name
    if nt.synopsis and not t.details_synced_at:
        t.synopsis = nt.synopsis
    if nt.release_date:
        t.release_date, t.year = nt.release_date, nt.release_date.year
    t.original_language = nt.original_language or t.original_language
    t.poster_path = nt.poster_path or t.poster_path
    t.backdrop_path = nt.backdrop_path or t.backdrop_path
    t.vote_average = nt.vote_average if nt.vote_average is not None else t.vote_average
    t.popularity = nt.popularity if nt.popularity is not None else t.popularity
    if not t.details_synced_at:  # a detail sync has the authoritative rating
        t.is_kids_safe = kids_safe(nt)
    t.metadata_synced_at = datetime.now(timezone.utc)


def _set_genres(db: Session, t: Title, names: list[str]) -> None:
    if not names:
        return
    gmap = ensure_genres(db, set(names))
    wanted = {gmap[n].id for n in names if n in gmap}
    have = {g.id for g in t.genres}
    if wanted == have:
        return
    t.genres = [gmap[n] for n in dict.fromkeys(names) if n in gmap]


def _add_ext(db: Session, t: Title, provider: str, ext: str) -> None:
    if any(e.provider == provider and e.external_id == ext for e in t.external_ids):
        return
    if any(e.provider == provider for e in t.external_ids):
        return  # one id per provider per title; a second one would make provider lookups ambiguous
    clash = db.scalar(select(TitleExternalId.id).where(
        TitleExternalId.provider == provider, TitleExternalId.external_id == ext))
    if clash:
        return
    t.external_ids.append(TitleExternalId(provider=provider, external_id=ext))


def upsert_titles(db: Session, items: list[NormalizedTitle]) -> list[tuple[Title, NormalizedTitle]]:
    """Maps provider results onto catalog rows (creating or merging) and returns (row, provider item) pairs.
    A concurrent request may insert the same external id first; on that unique violation we retry once and merge."""
    try:
        return _upsert_titles(db, items)
    except IntegrityError:
        db.rollback()
        return _upsert_titles(db, items)


def _upsert_titles(db: Session, items: list[NormalizedTitle]) -> list[tuple[Title, NormalizedTitle]]:
    if not items:
        return []
    by_provider: dict[str, list[str]] = defaultdict(list)
    for it in items:
        by_provider[it.provider].append(it.external_id)
    known: dict[tuple[str, str], Title] = {}
    for prov, ids in by_provider.items():
        rows = db.execute(
            select(TitleExternalId).options(joinedload(TitleExternalId.title))
            .where(TitleExternalId.provider == prov, TitleExternalId.external_id.in_(ids))
        ).scalars()
        for r in rows:
            known[(r.provider, r.external_id)] = r.title

    misses = [i for i in items if (i.provider, i.external_id) not in known]
    ensure_languages(db, {i.original_language for i in items if i.original_language})
    cands: dict[tuple, list[Title]] = defaultdict(list)
    if misses:  # one query finds same-name titles to merge into (year must agree when both are known)
        norms = {norm_name(i.name) for i in misses}
        for t in db.scalars(select(Title).options(selectinload(Title.external_ids)).where(Title.norm_name.in_(norms))):
            cands[(t.norm_name, t.type)].append(t)
    stale_before = datetime.now(timezone.utc) - timedelta(hours=6)

    pairs: list[tuple[Title, NormalizedTitle]] = []
    seen: set[uuid.UUID] = set()
    for it in items:
        key = (it.provider, it.external_id)
        t = known.get(key)
        if t is None:
            n = norm_name(it.name)
            for c in cands.get((n, it.type), []):
                # An id we have not seen, from a provider this candidate already has an id for, is a DIFFERENT
                # title that merely shares name and year (e.g. two films called "Beast"). Merge only across providers.
                if any(e.provider == it.provider for e in c.external_ids):
                    continue
                if c.year is None or it.release_date is None or c.year == it.release_date.year:
                    t = c
                    break
            if t is None:
                t = Title(
                    id=uuid.uuid4(), type=it.type, name=it.name, norm_name=n, source=it.provider,
                    original_language=it.original_language, status="published",
                )
                _apply_listing_fields(t, it)
                db.add(t)
                cands[(n, it.type)].append(t)
                # flush now so subsequent duplicates in this batch (and FK rows) see it
                db.flush()
            known[key] = t
            _add_ext(db, t, it.provider, it.external_id)
            for p, e in it.extra_ids.items():
                if p != "license_url":
                    _add_ext(db, t, p, e)
            _set_genres(db, t, it.genres)
            t.metadata_synced_at = t.metadata_synced_at or datetime.now(timezone.utc)
        elif t.metadata_synced_at is None or _aware(t.metadata_synced_at) < stale_before:
            _apply_listing_fields(t, it)
            _set_genres(db, t, it.genres)
        if t.id in seen:
            continue
        seen.add(t.id)
        pairs.append((t, it))
    db.commit()
    return pairs


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def apply_details(db: Session, t: Title, nt: NormalizedTitle) -> None:
    """Persist full details (cast, runtime, seasons, rating) from a provider detail response."""
    if t.source != "admin":
        _apply_listing_fields(t, nt)
        t.synopsis = nt.synopsis or t.synopsis
        t.runtime_minutes = nt.runtime or t.runtime_minutes
        t.age_rating = nt.age_rating or t.age_rating
        t.is_kids_safe = kids_safe(nt)
        t.audio_languages = nt.audio_languages or t.audio_languages
        _set_genres(db, t, nt.genres)
        if nt.cast:
            db.query(CastMember).filter(CastMember.title_id == t.id).delete()
            for i, c in enumerate(nt.cast):
                db.add(CastMember(title_id=t.id, person_name=c.name, character=c.character, position=i,
                                  external_person_id=c.person_id, profile_path=c.profile_path))
        if nt.crew:
            db.query(CrewMember).filter(CrewMember.title_id == t.id).delete()
            for i, c in enumerate(nt.crew):
                db.add(CrewMember(title_id=t.id, person_name=c.name, job=c.job, department=c.department, position=i,
                                  external_person_id=c.person_id, profile_path=c.profile_path))
        have = {s.number: s for s in db.scalars(select(Season).where(Season.title_id == t.id))}
        for s in nt.seasons:
            row = have.get(s.number) or Season(title_id=t.id, number=s.number)
            row.name, row.overview, row.air_date = s.name, s.overview, s.air_date
            row.poster_path, row.episode_count = s.poster_path, s.episode_count
            if s.number not in have:
                db.add(row)
    for p, e in nt.extra_ids.items():
        _add_ext(db, t, p, e)
    t.details_synced_at = datetime.now(timezone.utc)
    db.commit()


# ------------------------------------------------------------------ playability badges
def direct_access(db: Session, title_ids: list[uuid.UUID], country: str | None) -> dict[uuid.UUID, str]:
    """title_id -> entitlement for titles that have a verified, in-window, in-territory right AND an active asset."""
    if not title_ids:
        return {}
    from .rights import evaluate_rights  # local import avoids a cycle in tests

    with_assets = set(db.scalars(select(MediaAsset.title_id).where(
        MediaAsset.title_id.in_(title_ids), MediaAsset.is_active.is_(True)).distinct()))
    if not with_assets:
        return {}
    rights: dict[uuid.UUID, list[TitleRight]] = defaultdict(list)
    for r in db.scalars(select(TitleRight).where(TitleRight.title_id.in_(with_assets))):
        rights[r.title_id].append(r)
    now = datetime.now(timezone.utc)
    out = {}
    for tid in with_assets:
        # evaluate as a premium user to learn the best entitlement, then as free to learn if it's free
        if evaluate_rights(rights[tid], now, country, "free").allowed:
            out[tid] = "registered"
        elif evaluate_rights(rights[tid], now, country, "premium").allowed:
            out[tid] = "premium"
    return out


def to_card(t: Title, access: dict, overlay: NormalizedTitle | None = None) -> TitleCard:
    ent = access.get(t.id)
    direct = None
    if ent:
        direct = DirectAccess(entitlement=ent, label="Free to watch here" if ent == "registered" else "Premium")
    return TitleCard(
        id=t.id, type=t.type, name=(overlay.name if overlay and overlay.name else t.name), year=t.year,
        poster_url=image_url(t.poster_path, "poster"), backdrop_url=image_url(t.backdrop_path, "backdrop"),
        vote_average=t.vote_average, original_language=t.original_language, genres=[g.name for g in t.genres],
        age_rating=t.age_rating, is_kids_safe=t.is_kids_safe, runtime_minutes=t.runtime_minutes,
        release_date=t.release_date, direct=direct,
    )


def cards_from_pairs(db: Session, pairs, country: str | None, kids: bool, level: str = "all") -> list[TitleCard]:
    pairs = [(t, o) for t, o in pairs if t.status == "published" and (t.is_kids_safe or not kids)
             and title_allowed(t, level)]
    access = direct_access(db, [t.id for t, _ in pairs], country)
    return [to_card(t, access, o) for t, o in pairs]


def cards_from_titles(db: Session, titles: list[Title], country: str | None, kids: bool = False,
                      level: str = "all") -> list[TitleCard]:
    return cards_from_pairs(db, [(t, None) for t in titles], country, kids, level)


# ------------------------------------------------------------------ top 10
TOP_N = 10
TOP_DAYS = 7


def top_played(db: Session, country: str | None, kids: bool, level: str = "all") -> list[TitleCard]:
    """Titles most played on this platform in the last week, counted once per profile so one viewer cannot push a title
    up. Only what CineVerse itself streamed (playback sessions), in the viewer's country."""
    since = datetime.now(timezone.utc) - timedelta(days=TOP_DAYS)
    stmt = (select(PlaybackSession.title_id, func.count(func.distinct(PlaybackSession.profile_id)).label("viewers"))
            .where(PlaybackSession.issued_at >= since, PlaybackSession.profile_id.is_not(None))
            .group_by(PlaybackSession.title_id).order_by(text("viewers desc"), PlaybackSession.title_id).limit(TOP_N * 3))
    if country:
        stmt = stmt.where(PlaybackSession.country == country)
    ids = [r[0] for r in db.execute(stmt)]
    if not ids:
        return []
    by_id = {t.id: t for t in db.scalars(select(Title).where(Title.id.in_(ids), Title.status == "published")).unique()}
    titles = [by_id[i] for i in ids if i in by_id and (by_id[i].is_kids_safe or not kids) and title_allowed(by_id[i], level)]
    return cards_from_titles(db, titles[:TOP_N], country, kids, level)


TOP_MIN_PLAYED = 5  # below this many titles with real plays the row would be mostly trending, so it is not shown


def top10_items(played: list[dict], trending: list[dict]) -> list[dict]:
    """Items for the Top 10 row, or [] when too few titles have been played here to call it a ranking."""
    if len(played) < TOP_MIN_PLAYED:
        return []
    seen = {c["id"] for c in played}
    return (played + [i for i in trending if i["id"] not in seen])[:TOP_N]


# ------------------------------------------------------------------ queries
def local_titles(db: Session, *, type_: str | None = None, original_language: str | None = None,
                 genres: list[str] | None = None, year: int | None = None, q: str | None = None,
                 order: str = "popularity", limit: int = 20, offset: int = 0, kids: bool = False,
                 direct_only: bool = False) -> tuple[list[Title], int]:
    stmt = select(Title).where(Title.status == "published")
    if type_ == "documentary":
        genres = [*(genres or []), "Documentary"]
    elif type_ in ("movie", "series"):
        stmt = stmt.where(Title.type == type_)
    if original_language:
        stmt = stmt.where(Title.original_language == original_language)
    if year:
        stmt = stmt.where(Title.year == year)
    for g in genres or []:
        stmt = stmt.where(Title.id.in_(select(TitleGenre.title_id).join(Genre).where(Genre.name == g)))
    if q:
        n = norm_name(q)
        like = f"%{n}%"
        stmt = stmt.where(or_(Title.norm_name.like(like), func.lower(Title.original_name).like(f"%{q.lower()}%")))
    if kids:
        stmt = stmt.where(Title.is_kids_safe.is_(True))
    if direct_only:
        stmt = stmt.where(Title.id.in_(select(MediaAsset.title_id).where(MediaAsset.is_active.is_(True))),
                          Title.id.in_(select(TitleRight.title_id).where(TitleRight.status == "verified")))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = {"recent": Title.created_at.desc(), "rating": Title.vote_average.desc().nullslast()}.get(
        order, Title.popularity.desc().nullslast())
    rows = db.scalars(stmt.order_by(col, Title.id).limit(limit).offset(offset)).unique().all()
    return list(rows), total


def _provider_page(fn_name: str, *args, **kw) -> tuple[Page | None, str | None]:
    prov = get_registry().primary_metadata
    if prov is None:
        return None, "No metadata provider is configured. Set TMDB_READ_TOKEN to enable discovery."
    try:
        return getattr(prov, fn_name)(*args, **kw), None
    except ProviderError as e:
        return None, f"Metadata provider unavailable: {e}"


def section_page(db: Session, section: str, type_: str, page: int, language: str, country: str | None,
                 kids: bool, original_language: str | None = None, genres: list[str] | None = None,
                 year: int | None = None, origin_country: str | None = None, availability: str | None = None,
                 watch_region: str | None = None, level: str = "all") -> CatalogPage:
    genres = list(genres or [])
    if section in ("recent", "free"):
        unsupported = ("Country and availability filters are not applied to this section."
                       if (origin_country or availability) else None)
        rows, total = local_titles(db, type_=None if type_ in ("all", "") else type_, original_language=original_language,
                                   genres=genres, year=year, order="recent" if section == "recent" else "popularity",
                                   limit=20, offset=(page - 1) * 20, kids=kids, direct_only=(section == "free"))
        return CatalogPage(items=cards_from_titles(db, rows, country, kids, level), page=page,
                           total_pages=max(1, -(-total // 20)), message=unsupported)
    kinds = {"movie": ["movie"], "series": ["series"], "documentary": ["movie", "series"], "all": ["movie", "series"]}[type_]
    if type_ == "documentary":
        genres.append("Documentary")
    if kids:  # kids profiles browse family-friendly discovery instead of general lists
        genres = [g for g in genres] + ["Family"]
        section = "popular" if section == "trending" else section
    pairs, notes, total = [], [], 1
    for kind in kinds:
        pg, err = _provider_page("section", section, kind, page, language, original_language, genres, year,
                                 origin_country=origin_country, watch_region=watch_region or country,
                                 monetization=availability)
        if err:
            notes.append(err)
            continue
        total = max(total, pg.total_pages)
        pairs.extend(upsert_titles(db, pg.items))
    if not pairs and notes:  # degrade to what we already hold locally
        rows, tot = local_titles(db, type_=type_ if type_ != "all" else None, original_language=original_language,
                                 genres=genres, year=year, limit=20, offset=(page - 1) * 20, kids=kids)
        return CatalogPage(items=cards_from_titles(db, rows, country, kids, level), page=page,
                           total_pages=max(1, -(-tot // 20)), degraded=True, message=notes[0])
    if len(kinds) > 1 and section != "upcoming":
        pairs.sort(key=lambda p: -(p[0].popularity or 0))
    return CatalogPage(items=cards_from_pairs(db, pairs, country, kids, level), page=page, total_pages=total,
                       degraded=bool(notes), message=notes[0] if notes else None)


def search_page(db: Session, *, q: str | None, actor: str | None, genres: list[str], language: str,
                original_language: str | None, year: int | None, type_: str | None, page: int,
                country: str | None, kids: bool, origin_country: str | None = None, availability: str | None = None,
                watch_region: str | None = None, level: str = "all") -> CatalogPage:
    kinds = {"movie": ["movie"], "series": ["series"], "documentary": ["movie", "series"], None: [None]}[type_]
    if type_ == "documentary":
        genres = [*genres, "Documentary"]
    pairs, notes, total = [], [], 1
    for kind in kinds:
        if actor:
            for k in ([kind] if kind else ["movie", "series"]):
                pg, err = _provider_page("discover_by_person", actor, k, page, language)
                if err:
                    notes.append(err)
                else:
                    total = max(total, pg.total_pages)
                    pairs.extend(upsert_titles(db, pg.items))
        elif q:
            pg, err = _provider_page("search", q, kind, page, language, year)
            if err:
                notes.append(err)
            else:
                total = max(total, pg.total_pages)
                pairs.extend(upsert_titles(db, pg.items))
        else:
            for k in ([kind] if kind else ["movie", "series"]):
                pg, err = _provider_page("section", "popular", k, page, language, original_language, genres, year,
                                         origin_country=origin_country, watch_region=watch_region or country,
                                         monetization=availability)
                if err:
                    notes.append(err)
                else:
                    total = max(total, pg.total_pages)
                    pairs.extend(upsert_titles(db, pg.items))
    # post-filters that the provider's search endpoints cannot apply
    def ok(t: Title) -> bool:
        if original_language and t.original_language != original_language:
            return False
        if year and t.year != year:
            return False
        names = {g.name for g in t.genres}
        return all(g in names for g in genres)

    pairs = [(t, o) for t, o in pairs if ok(t)]
    # merge locally curated / imported titles (e.g. verified public-domain films) for text queries
    if q and page == 1:
        have = {t.id for t, _ in pairs}
        rows, _ = local_titles(db, type_=type_, original_language=original_language, genres=genres, year=year, q=q,
                               limit=10, kids=kids)
        pairs.extend((t, None) for t in rows if t.id not in have)
    cards = cards_from_pairs(db, pairs, country, kids, level)
    if notes and not cards and q:
        rows, tot = local_titles(db, type_=type_, q=q, kids=kids, limit=20)
        cards = cards_from_titles(db, rows, country, kids, level)
    msg = notes[0] if notes else None
    if not msg and (q or actor) and (origin_country or availability):
        msg = "Country and availability filters apply when browsing; they are not applied to text or actor searches."
    return CatalogPage(items=cards, page=page, total_pages=total, degraded=bool(notes), message=msg)


# ------------------------------------------------------------------ details
def title_ext(t: Title) -> dict[str, str]:
    return {e.provider: e.external_id for e in t.external_ids}


def ensure_playback_assets(db: Session, t: Title, ep: Episode | None = None):
    """Development shortcut (DEMO_SAMPLE_VIDEO=true): a public sample video for any title with no stream."""
    if not get_settings().demo_sample_video:
        return
    right = db.scalar(select(TitleRight).where(TitleRight.title_id == t.id, TitleRight.source == "platform"))
    if not right:
        db.add(TitleRight(
            title_id=t.id, status="verified", territories=["*"],
            license_type="licensed", entitlement="registered", source="platform"
        ))
    else:
        right.status = "verified"
        right.territories = ["*"]
        right.entitlement = "registered"
    target_ep_id = ep.id if ep else None
    if not db.scalar(select(MediaAsset.id).where(
        MediaAsset.title_id == t.id,
        MediaAsset.episode_id == target_ep_id,
        MediaAsset.is_active.is_(True)
    ).limit(1)):
        ep_param = f"&eid={ep.id}" if ep else ""
        db.add(MediaAsset(
            title_id=t.id,
            episode_id=target_ep_id,
            kind="mp4",
            url=f"https://vjs.zencdn.net/v/oceans.mp4?tid={t.id}{ep_param}",
            is_active=True
        ))
    db.commit()


def ensure_details(db: Session, t: Title, language: str = "en") -> bool:
    """Fetch provider details when never synced or stale. Returns False if refresh failed (cached data is used)."""
    s = get_settings()
    ensure_playback_assets(db, t)
    db.commit()
    fresh = t.details_synced_at and _aware(t.details_synced_at) > datetime.now(timezone.utc) - timedelta(days=s.details_refresh_days)
    ext = title_ext(t)
    has_crew = db.scalar(select(func.count(CrewMember.id)).where(CrewMember.title_id == t.id)) > 0
    if (fresh and has_crew) or "tmdb" not in ext or t.source == "admin":
        return True
    prov = get_registry().primary_metadata
    if prov is None:
        return False
    try:
        nt = prov.details(t.type, ext["tmdb"], "en-US" if language == "en" else language)
    except ProviderError:
        return False
    apply_details(db, t, nt)
    return True


def load_title_full(db: Session, title_id: uuid.UUID) -> Title | None:
    return db.scalar(select(Title).where(Title.id == title_id))


def to_detail(db: Session, t: Title, country: str | None) -> TitleDetail:
    cast = db.scalars(select(CastMember).where(CastMember.title_id == t.id).order_by(CastMember.position)).all()
    crew = db.scalars(select(CrewMember).where(CrewMember.title_id == t.id).order_by(CrewMember.position)).all()
    seasons = db.scalars(select(Season).where(Season.title_id == t.id).order_by(Season.number)).all()
    access = direct_access(db, [t.id], country)
    card = to_card(t, access)
    subs = sorted({s["lang"] for a in db.scalars(select(MediaAsset).where(MediaAsset.title_id == t.id, MediaAsset.is_active.is_(True)))
                   for s in (a.subtitles or [])})
    audio = sorted({*(t.audio_languages or []), *{l for a in db.scalars(select(MediaAsset).where(
        MediaAsset.title_id == t.id, MediaAsset.is_active.is_(True))) for l in (a.audio_languages or [])}})
    reg = get_registry()
    attrib = [p.attribution for p in reg.metadata if getattr(p, "attribution", "") and t.source != "admin" and p.name == "tmdb"]
    return TitleDetail(
        **card.model_dump(), synopsis=t.synopsis,
        cast=[CastOut(name=c.person_name, character=c.character, profile_url=image_url(c.profile_path, "profile")) for c in cast],
        crew=[CrewOut(name=c.person_name, job=c.job, department=c.department, profile_url=image_url(c.profile_path, "profile")) for c in crew],
        seasons=[SeasonOut(id=s.id, number=s.number, name=s.name, episode_count=s.episode_count, air_date=s.air_date) for s in seasons],
        audio_languages=audio, subtitle_languages=subs,
        external_ids={k: v for k, v in title_ext(t).items() if k in ("imdb", "tmdb")}, attribution=attrib,
    )


def ensure_episodes(db: Session, t: Title, season: Season, language: str = "en") -> bool:
    fresh = season.episodes_synced_at and _aware(season.episodes_synced_at) > datetime.now(timezone.utc) - timedelta(
        days=get_settings().details_refresh_days)
    if fresh:
        return True
    ext = title_ext(t).get("tmdb")
    prov = get_registry().primary_metadata
    if not ext or prov is None or t.source == "admin":
        return True
    try:
        eps = prov.season(ext, season.number, "en-US" if language == "en" else language)
    except ProviderError:
        return False
    have = {e.number: e for e in db.scalars(select(Episode).where(Episode.season_id == season.id))}
    for e in eps:
        row = have.get(e.number) or Episode(season_id=season.id, title_id=t.id, number=e.number)
        row.name, row.overview, row.air_date = e.name, e.overview, e.air_date
        row.runtime_minutes, row.still_path = e.runtime, e.still_path
        if e.number not in have:
            db.add(row)
    season.episodes_synced_at = datetime.now(timezone.utc)
    season.episode_count = len(eps) or season.episode_count
    db.commit()
    return True
