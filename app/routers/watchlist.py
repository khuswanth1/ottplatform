import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_profile, require_verified, resolve_country
from ..maturity import blocked, profile_level
from ..models import Profile, Title, User, WatchlistItem
from ..schemas import CatalogPage, Msg, WatchlistIn
from ..services import catalog as svc

router = APIRouter(prefix="/watchlist", tags=["watchlist"])
PAGE = 24


@router.get("", response_model=CatalogPage)
def list_items(request: Request, kind: Literal["watchlist", "favorite"] = "watchlist", page: int = Query(1, ge=1),
               _: User = Depends(require_verified), profile: Profile = Depends(get_profile),
               db: Session = Depends(get_db)):
    base = select(Title).join(WatchlistItem, WatchlistItem.title_id == Title.id).where(
        WatchlistItem.profile_id == profile.id, WatchlistItem.kind == kind, Title.status == "published")
    if profile.is_kids:
        base = base.where(Title.is_kids_safe.is_(True))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(WatchlistItem.added_at.desc()).limit(PAGE).offset((page - 1) * PAGE)).unique().all()
    return CatalogPage(items=svc.cards_from_titles(db, list(rows), resolve_country(request), profile.is_kids, profile_level(profile)),
                       page=page, total_pages=max(1, -(-total // PAGE)))


@router.get("/ids", response_model=dict)
def ids(_: User = Depends(require_verified), profile: Profile = Depends(get_profile), db: Session = Depends(get_db)):
    """Compact membership map so the UI can render add/remove buttons without fetching full cards."""
    out: dict[str, list[str]] = {"watchlist": [], "favorite": []}
    for tid, kind in db.execute(select(WatchlistItem.title_id, WatchlistItem.kind).where(WatchlistItem.profile_id == profile.id)):
        out[kind].append(str(tid))
    return out


@router.put("/{title_id}", response_model=Msg)
def add(title_id: uuid.UUID, body: WatchlistIn | None = None, _: User = Depends(require_verified),
        profile: Profile = Depends(get_profile), db: Session = Depends(get_db)):
    kind = (body or WatchlistIn()).kind
    t = db.get(Title, title_id)
    if not t or t.status != "published" or blocked(profile, t):
        raise HTTPException(404, "Title not found.")
    if not db.get(WatchlistItem, (profile.id, title_id, kind)):  # idempotent: no write when already present
        db.add(WatchlistItem(profile_id=profile.id, title_id=title_id, kind=kind))
        db.commit()
    return Msg(message="Saved.")


@router.delete("/{title_id}", response_model=Msg)
def remove(title_id: uuid.UUID, kind: Literal["watchlist", "favorite"] = "watchlist", _: User = Depends(require_verified),
           profile: Profile = Depends(get_profile), db: Session = Depends(get_db)):
    db.execute(delete(WatchlistItem).where(WatchlistItem.profile_id == profile.id, WatchlistItem.title_id == title_id,
                                           WatchlistItem.kind == kind))
    db.commit()
    return Msg(message="Removed.")
