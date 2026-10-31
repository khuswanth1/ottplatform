import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import AuditLog, AuthSession, Profile, User
from .ratelimit import client_ip
from .security import safe_eq, sha256

SESSION_COOKIE = "ott_session"
CSRF_COOKIE = "ott_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_COUNTRY = re.compile(r"^[A-Za-z]{2}$")


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_session(request: Request, db: Session) -> tuple[AuthSession, User] | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == sha256(raw)))
    now = datetime.now(timezone.utc)
    if not sess or sess.revoked_at or _aware(sess.expires_at) <= now:
        return None
    user = db.get(User, sess.user_id)
    if not user or not user.is_active:
        return None
    if (now - _aware(sess.last_seen_at)) > timedelta(minutes=5):  # avoid a DB write on every request
        sess.last_seen_at = now
        db.commit()
    return sess, user


def _check_csrf(request: Request, sess: AuthSession) -> None:
    if request.method in SAFE_METHODS:
        return
    sent = request.headers.get("x-csrf-token", "")
    cookie = request.cookies.get(CSRF_COOKIE, "")
    if not sent or not safe_eq(sent, sess.csrf_token) or not safe_eq(sent, cookie):
        raise HTTPException(403, "Missing or invalid CSRF token.")


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    found = load_session(request, db)
    if not found:
        return None
    sess, user = found
    _check_csrf(request, sess)
    request.state.session = sess
    return user


def get_current_user(user: User | None = Depends(get_optional_user)) -> User:
    if not user:
        raise HTTPException(401, "Authentication required.")
    return user


def require_verified(user: User = Depends(get_current_user)) -> User:
    if get_settings().require_email_verification and not user.email_verified_at:
        raise HTTPException(403, "Please verify your email address first.")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required.")
    return user


def _profile_for(db: Session, user: User, pid: str | None, request: Request | None = None) -> Profile | None:
    if not pid:
        return None
    try:
        uid = uuid.UUID(pid)
    except ValueError:
        raise HTTPException(400, "Invalid profile id.")
    # ownership check: a profile id belonging to someone else is indistinguishable from a missing one
    prof = db.scalar(select(Profile).where(Profile.id == uid, Profile.user_id == user.id))
    if not prof:
        raise HTTPException(404, "Profile not found.")
    if prof.pin_hash and request is not None:
        sess = getattr(request.state, "session", None)
        if not sess or sess.unlocked_profile_id != prof.id:
            raise HTTPException(403, {"code": "profile_locked", "message": "Enter this profile's PIN to continue."})
    return prof


def get_optional_profile(
    request: Request,
    user: User | None = Depends(get_optional_user),
    x_profile_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Profile | None:
    return _profile_for(db, user, x_profile_id, request) if user else None


def get_profile(
    request: Request,
    user: User = Depends(get_current_user),
    x_profile_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Profile:
    prof = _profile_for(db, user, x_profile_id, request)
    if not prof:
        raise HTTPException(400, "Select a profile first (X-Profile-Id header).")
    return prof


def resolve_country(request: Request) -> str:
    """Trusted country only: the CDN/proxy header when configured, else the configured default (dev)."""
    s = get_settings()
    if s.country_header:
        v = request.headers.get(s.country_header, "")
        if _COUNTRY.match(v):
            return v.upper()
    return s.default_country.upper()


def clean_country(value: str | None, fallback: str) -> str:
    if value and _COUNTRY.match(value):
        return value.upper()
    return fallback


def audit(db: Session, request: Request | None, actor: User | None, action: str, entity_type: str,
          entity_id: object = None, detail: dict | None = None) -> None:
    db.add(AuditLog(
        actor_user_id=actor.id if actor else None, action=action, entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None, detail=detail,
        ip=client_ip(request) if request else None,
    ))
