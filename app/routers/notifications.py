import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_profile, require_verified, resolve_country
from ..maturity import blocked
from ..models import Episode, Notification, Profile, Season, Title, User
from ..schemas import Msg, TitleCard
from ..services import catalog as svc
from ..services.notify import notify_profile_throttled

router = APIRouter(prefix="/notifications", tags=["notifications"])
LIMIT = 30


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str  # reminder_released | new_episode | new_in_list
    title: TitleCard
    episode_id: uuid.UUID | None = None
    episode_label: str | None = None  # "S2:E3 Name" for new_episode
    created_at: datetime
    read_at: datetime | None = None


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread: int


class ReadIn(BaseModel):
    ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    all: bool = False


@router.get("", response_model=NotificationList)
def list_notifications(request: Request, _: User = Depends(require_verified), profile: Profile = Depends(get_profile),
                       db: Session = Depends(get_db)):
    notify_profile_throttled(db, profile.id)
    rows = db.execute(select(Notification, Title, Episode, Season.number).join(Title, Title.id == Notification.title_id)
                      .outerjoin(Episode, Episode.id == Notification.episode_id).outerjoin(Season, Season.id == Episode.season_id)
                      .where(Notification.profile_id == profile.id, Title.status == "published")
                      .order_by(Notification.created_at.desc()).limit(LIMIT * 2)).unique().all()
    rows = [r for r in rows if not blocked(profile, r[1])][:LIMIT]
    cards = {c.id: c for c in svc.cards_from_titles(db, [r[1] for r in rows], resolve_country(request), profile.is_kids,
                                                    profile.maturity_level)}
    items = [NotificationOut(id=n.id, kind=n.kind, title=cards[t.id], episode_id=ep.id if ep else None,
                             episode_label=f"S{sn}:E{ep.number}" + (f" {ep.name}" if ep.name else "") if ep else None,
                             created_at=n.created_at, read_at=n.read_at)
             for n, t, ep, sn in rows if t.id in cards]
    return NotificationList(items=items, unread=sum(1 for i in items if i.read_at is None))


@router.post("/read", response_model=Msg)
def mark_read(body: ReadIn, _: User = Depends(require_verified), profile: Profile = Depends(get_profile),
              db: Session = Depends(get_db)):
    stmt = update(Notification).where(Notification.profile_id == profile.id, Notification.read_at.is_(None))
    if not body.all:
        stmt = stmt.where(Notification.id.in_(body.ids))
    db.execute(stmt.values(read_at=datetime.now(timezone.utc)))
    db.commit()
    return Msg(message="Marked as read.")
