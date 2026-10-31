import uuid

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import require_verified
from ..models import AuthSession, Profile, User
from ..ratelimit import rate_limit
from ..schemas import Msg, PinSet, PinUnlock, ProfileIn, ProfileOut, ProfilePatch
from ..security import hash_password, verify_password

router = APIRouter(prefix="/profiles", tags=["profiles"])


PIN_MAX_FAILS = 5
PIN_LOCK_MINUTES = 15


def _owned(db: Session, user: User, pid: uuid.UUID, request: Request | None = None) -> Profile:
    """request given => the profile must also be open in this session when it has a PIN (edit and delete)."""
    p = db.scalar(select(Profile).where(Profile.id == pid, Profile.user_id == user.id))
    if not p:
        raise HTTPException(404, "Profile not found.")
    if request is not None and p.pin_hash:
        sess = getattr(request.state, "session", None)
        if not sess or sess.unlocked_profile_id != p.id:
            raise HTTPException(403, {"code": "profile_locked", "message": "Enter this profile's PIN to continue."})
    return p


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("", response_model=list[ProfileOut])
def list_profiles(user: User = Depends(require_verified), db: Session = Depends(get_db)):
    return db.scalars(select(Profile).where(Profile.user_id == user.id).order_by(Profile.created_at)).all()


@router.post("", response_model=ProfileOut, status_code=201)
def create_profile(body: ProfileIn, user: User = Depends(require_verified), db: Session = Depends(get_db)):
    count = db.scalar(select(func.count()).select_from(Profile).where(Profile.user_id == user.id)) or 0
    if count >= get_settings().max_profiles:
        raise HTTPException(409, f"You can have at most {get_settings().max_profiles} profiles.")
    data = body.model_dump()
    level = data.pop("maturity_level") or ("kids" if data["is_kids"] else "all")
    p = Profile(user_id=user.id, **{**data, "maturity_level": level, "is_kids": level == "kids"})
    db.add(p)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You already have a profile with that name.")
    return p


@router.patch("/{profile_id}", response_model=ProfileOut)
def update_profile(profile_id: uuid.UUID, body: ProfilePatch, request: Request,
                   user: User = Depends(require_verified), db: Session = Depends(get_db)):
    p = _owned(db, user, profile_id, request)
    data = body.model_dump(exclude_unset=True)
    level = data.pop("maturity_level", None)
    kids = data.pop("is_kids", None)
    if level is None and kids is not None:  # legacy flag: on -> kids, off -> back to unrestricted if it was kids
        level = "kids" if kids else ("all" if p.maturity_level == "kids" else p.maturity_level)
    if level is not None:
        p.maturity_level, p.is_kids = level, level == "kids"
    for k, v in data.items():
        if v is not None:
            setattr(p, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You already have a profile with that name.")
    return p


@router.delete("/{profile_id}", response_model=Msg)
def delete_profile(profile_id: uuid.UUID, request: Request, user: User = Depends(require_verified),
                   db: Session = Depends(get_db)):
    p = _owned(db, user, profile_id, request)
    count = db.scalar(select(func.count()).select_from(Profile).where(Profile.user_id == user.id)) or 0
    if count <= 1:
        raise HTTPException(409, "You must keep at least one profile.")
    db.delete(p)
    db.commit()
    return Msg(message="Profile deleted.")


@router.put("/{profile_id}/pin", response_model=ProfileOut, dependencies=[Depends(rate_limit("pin-set", 10, 60))])
def set_pin(profile_id: uuid.UUID, body: PinSet, request: Request, user: User = Depends(require_verified),
            db: Session = Depends(get_db)):
    """Set, change or (pin = null) remove the PIN. Needs the account password, so someone sitting at an open
    session cannot lock the owner out or strip the lock."""
    p = _owned(db, user, profile_id)
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(403, "That password is not correct.")
    p.pin_hash = hash_password(body.pin) if body.pin else None
    p.pin_failed, p.pin_locked_until = 0, None
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.unlocked_profile_id == p.id)
               .values(unlocked_profile_id=None))  # every device must enter the (new) PIN again
    sess = getattr(request.state, "session", None)
    if sess is not None and body.pin:
        db.get(AuthSession, sess.id).unlocked_profile_id = p.id  # the owner just proved who they are
    db.commit()
    return p


@router.post("/{profile_id}/unlock", response_model=Msg, dependencies=[Depends(rate_limit("pin-unlock", 30, 60))])
def unlock(profile_id: uuid.UUID, body: PinUnlock, request: Request, user: User = Depends(require_verified),
           db: Session = Depends(get_db)):
    """Opens one locked profile for this session (and closes any other). 5 wrong PINs lock the profile for 15 minutes."""
    p = _owned(db, user, profile_id)
    sess = db.get(AuthSession, request.state.session.id)
    if not p.pin_hash:
        return Msg(message="This profile has no PIN.")
    now = datetime.now(timezone.utc)
    if p.pin_locked_until and _aware(p.pin_locked_until) > now:
        raise HTTPException(429, f"Too many wrong PINs. Try again in {PIN_LOCK_MINUTES} minutes or reset the PIN with your account password.")
    if not verify_password(body.pin, p.pin_hash):
        p.pin_failed += 1
        if p.pin_failed >= PIN_MAX_FAILS:
            p.pin_locked_until, p.pin_failed = now + timedelta(minutes=PIN_LOCK_MINUTES), 0
        db.commit()
        raise HTTPException(403, "That PIN is not correct.")
    p.pin_failed, p.pin_locked_until = 0, None
    sess.unlocked_profile_id = p.id
    db.commit()
    return Msg(message="Unlocked.")
