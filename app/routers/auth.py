from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import CSRF_COOKIE, SESSION_COOKIE, get_current_user, audit
from ..mailer import send_mail
from ..models import AuthSession, EmailToken, Profile, User
from ..ratelimit import client_ip, limit_key, rate_limit
from ..schemas import EmailIn, LoginIn, Msg, RegisterIn, ResetIn, TokenIn, UserOut
from ..security import (
    hash_password, needs_rehash, new_token, sha256, validate_password_strength, verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FAILS, LOCK_MINUTES = 5, 15


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, role=u.role, plan=u.plan, email_verified=bool(u.email_verified_at))


def _make_token(db: Session, user: User, purpose: str, hours: int) -> str:
    raw = new_token()
    db.add(EmailToken(user_id=user.id, purpose=purpose, token_hash=sha256(raw),
                      expires_at=datetime.now(timezone.utc) + timedelta(hours=hours)))
    db.commit()
    return raw


def _consume_token(db: Session, raw: str, purpose: str) -> User:
    t = db.scalar(select(EmailToken).where(EmailToken.token_hash == sha256(raw), EmailToken.purpose == purpose))
    now = datetime.now(timezone.utc)
    exp = t.expires_at if t and t.expires_at.tzinfo else (t.expires_at.replace(tzinfo=timezone.utc) if t else None)
    if not t or t.used_at or exp <= now:
        raise HTTPException(400, "This link is invalid or has expired.")
    # compare-and-set: of two concurrent requests with the same link only one flips used_at, the other gets 0 rows
    claimed = db.execute(update(EmailToken).where(EmailToken.id == t.id, EmailToken.used_at.is_(None))
                         .values(used_at=now).execution_options(synchronize_session=False)).rowcount
    if claimed != 1:
        raise HTTPException(400, "This link is invalid or has expired.")
    user = db.get(User, t.user_id)
    if not user:
        raise HTTPException(400, "This link is invalid or has expired.")
    return user


def _send_verification(db: Session, user: User, bg: BackgroundTasks) -> None:
    raw = _make_token(db, user, "verify", 48)
    link = f"{get_settings().frontend_url}/verify-email?token={raw}"
    bg.add_task(send_mail, user.email, "Verify your email", f"Welcome! Confirm your email address:\n\n{link}\n")


def _start_session(db: Session, request: Request, response: Response, user: User) -> AuthSession:
    s = get_settings()
    raw, csrf = new_token(), new_token(24)
    sess = AuthSession(
        user_id=user.id, token_hash=sha256(raw), csrf_token=csrf, ip=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:256],
        expires_at=datetime.now(timezone.utc) + timedelta(hours=s.session_ttl_hours),
    )
    db.add(sess)
    db.commit()
    kw = dict(max_age=s.session_ttl_hours * 3600, secure=s.secure_cookies, samesite="lax", path="/",
              domain=s.cookie_domain or None)
    response.set_cookie(SESSION_COOKIE, raw, httponly=True, **kw)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **kw)
    return sess


def _clear_cookies(response: Response) -> None:
    s = get_settings()
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", domain=s.cookie_domain or None)


@router.post("/register", status_code=202, response_model=Msg, dependencies=[Depends(rate_limit("register", 5, 60))])
def register(body: RegisterIn, bg: BackgroundTasks, db: Session = Depends(get_db)):
    if err := validate_password_strength(body.password):
        raise HTTPException(422, err)
    email = body.email.lower()
    generic = Msg(message="If the address can be registered, a verification email is on its way.")
    if db.scalar(select(User.id).where(User.email == email)):
        return generic  # do not reveal whether the address already has an account
    s = get_settings()
    verified_at = datetime.now(timezone.utc) if not s.require_email_verification else None
    user = User(email=email, password_hash=hash_password(body.password), email_verified_at=verified_at)
    db.add(user)
    db.flush()
    db.add(Profile(user_id=user.id, name="Me", avatar="avatar-1"))
    db.commit()
    if s.require_email_verification:
        _send_verification(db, user, bg)
    return generic


@router.post("/verify-email", response_model=Msg)
def verify_email(body: TokenIn, db: Session = Depends(get_db)):
    user = _consume_token(db, body.token, "verify")
    user.email_verified_at = user.email_verified_at or datetime.now(timezone.utc)
    db.commit()
    return Msg(message="Email verified. You can sign in now.")


@router.post("/resend-verification", status_code=202, response_model=Msg,
             dependencies=[Depends(rate_limit("resend", 3, 60))])
def resend(body: EmailIn, bg: BackgroundTasks, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user and not user.email_verified_at:
        _send_verification(db, user, bg)
    return Msg(message="If the account needs verification, a new email is on its way.")


@router.post("/login", response_model=dict, dependencies=[Depends(rate_limit("login", 20, 60))])
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    limit_key("login-email", email, 10, 900)
    user = db.scalar(select(User).where(User.email == email))
    now = datetime.now(timezone.utc)
    locked = user and user.locked_until and (
        user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=timezone.utc)) > now
    ok = verify_password(body.password, user.password_hash if user else None)
    if not user or locked or not ok:
        if user and not locked:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILS:
                user.locked_until, user.failed_logins = now + timedelta(minutes=LOCK_MINUTES), 0
            db.commit()
        raise HTTPException(401, "Invalid email or password, or the account is temporarily locked.")
    if not user.is_active:
        raise HTTPException(403, "This account has been disabled.")
    s = get_settings()
    if not user.email_verified_at:
        if s.require_email_verification:
            raise HTTPException(403, detail={"code": "email_not_verified", "message": "Please verify your email first."})
        user.email_verified_at = now
        db.commit()
    user.failed_logins, user.locked_until = 0, None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    sess = _start_session(db, request, response, user)
    return {"user": _user_out(user), "csrf_token": sess.csrf_token}


@router.post("/logout", response_model=Msg)
def logout(request: Request, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sess = request.state.session
    sess.revoked_at = datetime.now(timezone.utc)
    db.commit()
    _clear_cookies(response)
    return Msg(message="Signed out.")


@router.get("/me", response_model=dict)
def me(request: Request, user: User = Depends(get_current_user)):
    return {"user": _user_out(user), "csrf_token": request.state.session.csrf_token}


@router.post("/forgot-password", status_code=202, response_model=Msg,
             dependencies=[Depends(rate_limit("forgot", 3, 60))])
def forgot(body: EmailIn, bg: BackgroundTasks, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user and user.is_active:
        raw = _make_token(db, user, "reset", 1)
        link = f"{get_settings().frontend_url}/reset-password?token={raw}"
        bg.add_task(send_mail, user.email, "Reset your password",
                    f"Use this link within one hour to choose a new password:\n\n{link}\n\n"
                    "If you did not request this, ignore this email.")
    return Msg(message="If an account exists for that address, a reset email is on its way.")


@router.post("/reset-password", response_model=Msg, dependencies=[Depends(rate_limit("reset", 10, 60))])
def reset(body: ResetIn, db: Session = Depends(get_db)):
    if err := validate_password_strength(body.password):
        raise HTTPException(422, err)
    user = _consume_token(db, body.token, "reset")
    user.password_hash = hash_password(body.password)
    user.failed_logins, user.locked_until = 0, None
    # a reset signs the user out everywhere
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
               .values(revoked_at=datetime.now(timezone.utc)))
    db.commit()
    return Msg(message="Password updated. Please sign in.")
