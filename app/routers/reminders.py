import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_profile, require_verified
from ..maturity import blocked
from ..models import Profile, Reminder, Title, User

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.get("/ids", response_model=list[uuid.UUID])
def ids(_: User = Depends(require_verified), profile: Profile = Depends(get_profile), db: Session = Depends(get_db)):
    """Titles this profile is still waiting for (a reminder stops counting once its notification was created)."""
    return db.scalars(select(Reminder.title_id).where(Reminder.profile_id == profile.id, Reminder.notified_at.is_(None))).all()


@router.put("/{title_id}", status_code=204)
def remind(title_id: uuid.UUID, _: User = Depends(require_verified), profile: Profile = Depends(get_profile),
           db: Session = Depends(get_db)):
    t = db.get(Title, title_id)
    if not t or t.status != "published" or blocked(profile, t):
        raise HTTPException(404, "Title not found.")
    if not t.release_date or t.release_date <= datetime.now(timezone.utc).date():
        raise HTTPException(409, "This title is already out or has no release date yet, so there is nothing to wait for.")
    if not db.get(Reminder, (profile.id, title_id)):  # idempotent
        db.add(Reminder(profile_id=profile.id, title_id=title_id))
        db.commit()


@router.delete("/{title_id}", status_code=204)
def cancel(title_id: uuid.UUID, _: User = Depends(require_verified), profile: Profile = Depends(get_profile),
           db: Session = Depends(get_db)):
    db.execute(delete(Reminder).where(Reminder.profile_id == profile.id, Reminder.title_id == title_id))
    db.commit()
