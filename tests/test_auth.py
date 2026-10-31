import re

from app.models import AuthSession, User
from conftest import PASSWORD, Browser, signup


def test_register_verify_login_logout(mails):
    b = signup(mails)
    me = b.get("/auth/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == "user@example.com"
    assert b.post("/auth/logout").status_code == 200
    assert b.get("/auth/me").status_code == 401


def test_unverified_cannot_login(mails):
    b = signup(mails, verify=False)
    r = b.post("/auth/login", json={"email": "user@example.com", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "email_not_verified"


def test_register_does_not_reveal_existing_accounts(mails):
    signup(mails)
    b = Browser()
    r = b.post("/auth/register", json={"email": "user@example.com", "password": PASSWORD})
    assert r.status_code == 202  # same response as a fresh address
    assert len(mails) == 1  # and no second verification email


def test_weak_password_rejected(mails):
    b = Browser()
    assert b.post("/auth/register", json={"email": "a@example.com", "password": "short"}).status_code == 422


def test_password_is_argon2id(mails, db):
    signup(mails)
    assert db.query(User).one().password_hash.startswith("$argon2id$")


def test_wrong_password_and_lockout(mails):
    signup(mails)
    b = Browser()
    for _ in range(5):
        assert b.post("/auth/login", json={"email": "user@example.com", "password": "wrong-password-1"}).status_code == 401
    # even the right password is refused while locked
    assert b.post("/auth/login", json={"email": "user@example.com", "password": PASSWORD}).status_code == 401


def test_same_error_for_unknown_user(mails):
    b = Browser()
    r1 = b.post("/auth/login", json={"email": "nobody@example.com", "password": "whatever-123"})
    signup(mails)
    r2 = Browser().post("/auth/login", json={"email": "user@example.com", "password": "wrong-password-1"})
    assert r1.status_code == r2.status_code == 401 and r1.json() == r2.json()


def test_csrf_required_for_unsafe_methods(mails):
    b = signup(mails)
    b.csrf = ""
    assert b.post("/profiles", json={"name": "Kid"}).status_code == 403
    b.csrf = "wrong"
    assert b.post("/profiles", json={"name": "Kid"}).status_code == 403


def test_foreign_origin_blocked(mails):
    b = signup(mails)
    r = b.post("/profiles", json={"name": "Kid"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_session_cookie_flags(mails):
    b = Browser()
    b.post("/auth/register", json={"email": "c@example.com", "password": PASSWORD})
    token = re.search(r"token=([\w-]+)", mails[-1][2]).group(1)
    b.post("/auth/verify-email", json={"token": token})
    r = b.post("/auth/login", json={"email": "c@example.com", "password": PASSWORD})
    sc = [h for h in r.headers.get_list("set-cookie") if h.startswith("ott_session")][0].lower()
    assert "httponly" in sc and "samesite=lax" in sc


def test_password_reset_revokes_sessions_and_token_single_use(mails):
    b = signup(mails)
    other = Browser()
    other.post("/auth/forgot-password", json={"email": "user@example.com"})
    token = re.search(r"token=([\w-]+)", mails[-1][2]).group(1)
    assert other.post("/auth/reset-password", json={"token": token, "password": "a brand new passphrase"}).status_code == 200
    assert b.get("/auth/me").status_code == 401  # old session revoked
    assert other.post("/auth/reset-password", json={"token": token, "password": "another new passphrase"}).status_code == 400
    assert Browser().post("/auth/login", json={"email": "user@example.com", "password": "a brand new passphrase"}).status_code == 200


def test_forgot_password_is_generic(mails):
    r = Browser().post("/auth/forgot-password", json={"email": "ghost@example.com"})
    assert r.status_code == 202 and not mails


def test_session_tokens_stored_hashed(mails, db):
    b = signup(mails)
    raw = b.c.cookies.get("ott_session")
    assert raw and db.query(AuthSession).filter_by(token_hash=raw).first() is None


def test_login_rate_limited(mails):
    from app.main import app
    app.state.enforce_limits = True
    b = Browser()
    codes = [b.post("/auth/login", json={"email": f"x{i}@example.com", "password": "whatever-123"}).status_code for i in range(25)]
    assert 429 in codes
