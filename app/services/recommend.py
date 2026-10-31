"""Per-profile recommendations from what this profile did on the platform. No ML and no provider calls: a taste score
per genre from history, ratings and lists, then local titles ranked by the genres they carry.

Signals (weight per title, added to each of its genres):  loved +4, liked +3, favorite +3, on My list +2,
finished +2, started +1, disliked -3.  Titles the profile already played, listed or rated are never suggested."""
import uuid
from collections import defaultdict
from math import sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..maturity import title_allowed
from ..models import Profile, Title, TitleGenre, TitleRating, WatchlistItem, WatchProgress
from ..schemas import TitleCard
from . import catalog as svc

CANDIDATES = 300
MIN_SIGNALS = 1  # titles the profile has interacted with; fewer than this and there is nothing to base a row on
_RATING_W = {2: 4, 1: 3, -1: -3}
_LIST_W = {"favorite": 3, "watchlist": 2}


def _genres(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, set[int]]:
    out: dict[uuid.UUID, set[int]] = defaultdict(set)
    if ids:
        for tid, gid in db.execute(select(TitleGenre.title_id, TitleGenre.genre_id).where(TitleGenre.title_id.in_(ids))):
            out[tid].add(gid)
    return out


def taste(db: Session, profile: Profile) -> tuple[dict[int, float], set[uuid.UUID]]:
    """(genre id -> score, ids of every title the profile has touched)."""
    weight: dict[uuid.UUID, float] = defaultdict(float)
    for tid, done in db.execute(select(WatchProgress.title_id, WatchProgress.completed)
                                .where(WatchProgress.profile_id == profile.id, WatchProgress.hidden_at.is_(None))):
        weight[tid] += 2 if done else 1
    for tid, v in db.execute(select(TitleRating.title_id, TitleRating.value).where(TitleRating.profile_id == profile.id)):
        weight[tid] += _RATING_W.get(v, 0)
    for tid, kind in db.execute(select(WatchlistItem.title_id, WatchlistItem.kind).where(WatchlistItem.profile_id == profile.id)):
        weight[tid] += _LIST_W.get(kind, 0)
    touched = set(weight)
    # a removed activity entry still counts as "already seen": do not suggest it straight back
    touched |= set(db.scalars(select(WatchProgress.title_id).where(WatchProgress.profile_id == profile.id)))
    by_title = _genres(db, set(weight))
    score: dict[int, float] = defaultdict(float)
    for tid, w in weight.items():
        for gid in by_title.get(tid, ()):
            score[gid] += w
    return score, touched


def recommend(db: Session, profile: Profile, country: str | None, limit: int = 20) -> list[TitleCard]:
    score, touched = taste(db, profile)
    liked = {g for g, s in score.items() if s > 0}
    if len(touched) < MIN_SIGNALS or not liked:
        return []
    stmt = (select(Title).join(TitleGenre, TitleGenre.title_id == Title.id)
            .where(TitleGenre.genre_id.in_(liked), Title.status == "published", Title.id.not_in(touched))
            .group_by(Title.id).order_by(Title.popularity.desc().nullslast(), Title.id).limit(CANDIDATES))
    if profile.is_kids:
        stmt = stmt.where(Title.is_kids_safe.is_(True))
    cands = [t for t in db.scalars(stmt).unique() if title_allowed(t, getattr(profile, "maturity_level", "all"))]
    gmap = _genres(db, {t.id for t in cands})
    ranked = []
    for t in cands:
        gs = gmap.get(t.id, set())
        s = sum(score.get(g, 0) for g in gs)
        if s <= 0:
            continue  # a title that mixes a liked genre with a disliked one can net out to nothing
        # sqrt keeps a six-genre title from beating a focused match; popularity only breaks near-ties
        ranked.append((s / sqrt(len(gs)) + min(t.popularity or 0, 100) / 1000, t))
    ranked.sort(key=lambda r: -r[0])
    return svc.cards_from_titles(db, [t for _, t in ranked[:limit]], country, profile.is_kids, profile.maturity_level)
