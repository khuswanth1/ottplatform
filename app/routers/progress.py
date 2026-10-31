from datetime import datetime, timezone

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import get_profile, require_verified, resolve_country
from ..maturity import blocked, profile_level
from ..models import Episode, Profile, Season, Title, User, WatchProgress
from ..schemas import Msg, ProgressIn, ProgressOut
from ..services import catalog as svc

router = APIRouter(prefix="/watch-progress", tags=["watch-progress"])


def next_episode(db: Session, ep: Episode) -> Episode | None:
    season = db.get(Season, ep.season_id)
    nxt = db.scalar(select(Episode).where(Episode.season_id == ep.season_id, Episode.number > ep.number)
                    .order_by(Episode.number).limit(1))
    if nxt:
        return nxt
    ns = db.scalar(select(Season).where(Season.title_id == ep.title_id, Season.number > season.number)
                   .order_by(Season.number).limit(1))
    return db.scalar(select(Episode).where(Episode.season_id == ns.id).order_by(Episode.number).limit(1)) if ns else None


def previous_episode(db: Session, ep: Episode) -> Episode | None:
    season = db.get(Season, ep.season_id)
    prv = db.scalar(select(Episode).where(Episode.season_id == ep.season_id, Episode.number < ep.number)
                    .order_by(Episode.number.desc()).limit(1))
    if prv:
        return prv
    ps = db.scalar(select(Season).where(Season.title_id == ep.title_id, Season.number < season.number)
                   .order_by(Season.number.desc()).limit(1))
    return db.scalar(select(Episode).where(Episode.season_id == ps.id).order_by(Episode.number.desc()).limit(1)) if ps else None


def _label(db: Session, ep: Episode | None) -> str | None:
    if not ep:
        return None
    s = db.get(Season, ep.season_id)
    return f"S{s.number}:E{ep.number}" + (f" {ep.name}" if ep.name else "")


@router.put("", response_model=Msg)
def save(body: ProgressIn, _: User = Depends(require_verified), profile: Profile = Depends(get_profile),
         db: Session = Depends(get_db)):
    """Called every ~15 s and on pause/exit. Skips the write when nothing meaningful changed."""
    t = db.get(Title, body.title_id)
    if not t or t.status != "published" or blocked(profile, t):
        raise HTTPException(404, "Title not found.")
    if body.episode_id:
        ep = db.get(Episode, body.episode_id)
        if not ep or ep.title_id != t.id:
            raise HTTPException(404, "Episode not found.")
    elif t.type == "series":
        raise HTTPException(400, "episode_id is required for series.")
    key = str(body.episode_id) if body.episode_id else "-"
    done = body.duration_seconds > 0 and body.position_seconds / body.duration_seconds >= 0.95
    row = db.scalar(select(WatchProgress).where(WatchProgress.profile_id == profile.id,
                                                 WatchProgress.title_id == t.id, WatchProgress.episode_key == key))
    if row:
        if (abs(row.position_seconds - body.position_seconds) < get_settings().progress_min_delta_s and row.completed == done
                and row.hidden_at is None):
            return Msg(message="unchanged")
        row.hidden_at = None  # watching it again brings it back into the activity list
    else:
        row = WatchProgress(profile_id=profile.id, title_id=t.id, episode_id=body.episode_id, episode_key=key)
        db.add(row)
    row.position_seconds, row.duration_seconds, row.completed = body.position_seconds, body.duration_seconds, done
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return Msg(message="saved")


@router.get("", response_model=list[ProgressOut])
def list_progress(request: Request, history: bool = False, limit: int = Query(20, ge=1, le=100),
                  _: User = Depends(require_verified), profile: Profile = Depends(get_profile),
                  db: Session = Depends(get_db)):
    """history=false -> Continue Watching (one entry per title; finished episodes roll to the next one).
    history=true -> full watch history, newest first."""
    rows = db.scalars(select(WatchProgress).where(WatchProgress.profile_id == profile.id, WatchProgress.hidden_at.is_(None))
                      .order_by(WatchProgress.updated_at.desc()).limit(limit * 4 if not history else limit)).all()
    country = resolve_country(request)
    out, seen = [], set()
    titles = {t.id: t for t in db.scalars(select(Title).where(Title.id.in_({r.title_id for r in rows}),
                                                              Title.status == "published"))}
    for r in rows:
        t = titles.get(r.title_id)
        if not t or blocked(profile, t):
            continue
        ep_id, pos, dur, done = r.episode_id, r.position_seconds, r.duration_seconds, r.completed
        if not history:
            if t.id in seen:
                continue
            seen.add(t.id)
            if done:
                nxt = next_episode(db, db.get(Episode, r.episode_id)) if r.episode_id else None
                if not nxt:
                    continue
                ep_id, pos, dur, done = nxt.id, 0, 0, False
        ep = db.get(Episode, ep_id) if ep_id else None
        card = svc.cards_from_titles(db, [t], country, profile.is_kids, profile_level(profile))[0]
        out.append(ProgressOut(id=r.id, title=card, episode_id=ep_id, episode_label=_label(db, ep), position_seconds=pos,
                               duration_seconds=dur, completed=done, updated_at=r.updated_at))
        if len(out) >= limit:
            break
    return out


@router.get("/title/{title_id}", response_model=ProgressOut | None)
def get_title_progress(title_id: uuid.UUID, request: Request, _: User = Depends(require_verified),
                       profile: Profile = Depends(get_profile), db: Session = Depends(get_db)):
    """Return current watch progress for a single title under the active profile."""
    row = db.scalar(select(WatchProgress).where(
        WatchProgress.profile_id == profile.id,
        WatchProgress.title_id == title_id,
        WatchProgress.hidden_at.is_(None)
    ).order_by(WatchProgress.updated_at.desc()).limit(1))
    if not row:
        return None
    t = db.get(Title, title_id)
    if not t or t.status != "published" or blocked(profile, t):
        return None
    ep_id, pos, dur, done = row.episode_id, row.position_seconds, row.duration_seconds, row.completed
    if done and t.type == "series":
        nxt = next_episode(db, db.get(Episode, row.episode_id)) if row.episode_id else None
        if nxt:
            ep_id, pos, dur, done = nxt.id, 0, 0, False
    country = resolve_country(request)
    card = svc.cards_from_titles(db, [t], country, profile.is_kids, profile_level(profile))[0]
    ep = db.get(Episode, ep_id) if ep_id else None
    return ProgressOut(id=row.id, title=card, episode_id=ep_id, episode_label=_label(db, ep),
                       position_seconds=pos, duration_seconds=dur, completed=done, updated_at=row.updated_at)


@router.delete("/{progress_id}", response_model=Msg)
def hide_entry(progress_id: uuid.UUID, _: User = Depends(require_verified), profile: Profile = Depends(get_profile),
               db: Session = Depends(get_db)):
    """Remove one entry from viewing activity and Continue Watching. Idempotent; foreign ids are a 404."""
    row = db.scalar(select(WatchProgress).where(WatchProgress.id == progress_id, WatchProgress.profile_id == profile.id))
    if not row:
        raise HTTPException(404, "Entry not found.")
    if row.hidden_at is None:
        row.hidden_at = datetime.now(timezone.utc)
        db.commit()
    return Msg(message="Removed.")


@router.delete("", response_model=Msg)
def hide_title(title_id: uuid.UUID, _: User = Depends(require_verified), profile: Profile = Depends(get_profile),
               db: Session = Depends(get_db)):
    """Remove every episode of one title (a whole series) from viewing activity."""
    db.execute(update(WatchProgress).where(WatchProgress.profile_id == profile.id, WatchProgress.title_id == title_id,
                                           WatchProgress.hidden_at.is_(None)).values(hidden_at=datetime.now(timezone.utc)))
    db.commit()
    return Msg(message="Removed.")
