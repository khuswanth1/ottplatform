import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_profile, require_verified
from ..maturity import blocked
from ..models import Profile, Title, TitleRating, User, now
from ..schemas import RatingIn, RatingOut

router = APIRouter(prefix="/titles", tags=["ratings"])


def _title(db: Session, profile: Profile, title_id: uuid.UUID) -> Title:
    t = db.get(Title, title_id)
    if not t or t.status != "published" or blocked(profile, t):
        raise HTTPException(404, "Title not found.")
    return t


@router.get("/{title_id}/rating", response_model=RatingOut)
def get_rating(title_id: uuid.UUID, _: User = Depends(require_verified), profile: Profile = Depends(get_profile),
               db: Session = Depends(get_db)):
    r = db.get(TitleRating, (profile.id, title_id))
    return RatingOut(value=r.value if r else None)


@router.put("/{title_id}/rating", response_model=RatingOut)
def set_rating(title_id: uuid.UUID, body: RatingIn, _: User = Depends(require_verified),
               profile: Profile = Depends(get_profile), db: Session = Depends(get_db)):
    _title(db, profile, title_id)
    r = db.get(TitleRating, (profile.id, title_id))
    if r:
        r.value, r.rated_at = body.value, now()
    else:
        db.add(TitleRating(profile_id=profile.id, title_id=title_id, value=body.value))
    db.commit()
    return RatingOut(value=body.value)


@router.delete("/{title_id}/rating", response_model=RatingOut)
def clear_rating(title_id: uuid.UUID, _: User = Depends(require_verified), profile: Profile = Depends(get_profile),
                 db: Session = Depends(get_db)):
    r = db.get(TitleRating, (profile.id, title_id))
    if r:
        db.delete(r)
        db.commit()
    return RatingOut(value=None)
