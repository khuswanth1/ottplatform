import hashlib
import hmac
import secrets
import time
from urllib.parse import urlencode, urlsplit, urlunsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

# Argon2id with OWASP-recommended minimums (m=19MiB, t=2, p=1); tune upward per hardware.
_ph = PasswordHasher(type=Type.ID, memory_cost=19456, time_cost=2, parallelism=1)
_DUMMY = _ph.hash("dummy-password-for-timing")


_COMMON = {
    "password123", "1234567890", "qwertyuiop", "password12", "password1234", "passw0rd123", "1q2w3e4r5t", "0123456789",
    "12345678910", "123456789012", "iloveyou123", "welcome123", "letmein1234", "adminadmin", "administrator", "qwerty12345",
    "abcdefghij", "abc1234567", "1234512345", "0000000000", "1111111111", "aaaaaaaaaa", "changeme123", "netflix1234",
}


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str | None) -> bool:
    """Verifies against a dummy hash when the user does not exist, so timing doesn't reveal accounts."""
    try:
        ok = _ph.verify(hashed or _DUMMY, pw)
    except (VerificationError, InvalidHashError):
        return False
    return ok and hashed is not None


def needs_rehash(hashed: str) -> bool:
    return _ph.check_needs_rehash(hashed)


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def safe_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _media_sig(secret: str, path: str, exp: int, sid: str) -> str:
    return hmac.new(secret.encode(), f"{path}:{exp}:{sid}".encode(), hashlib.sha256).hexdigest()


def sign_media_url(url: str, secret: str, ttl_s: int, sid: str = "") -> str:
    """HMAC-SHA256 token over path + expiry + playback session id. The edge (nginx auth_request / Caddy forward_auth ->
    GET /api/v1/playback/authorize, or a CDN worker holding the same secret) validates it, so the token is useless for
    other paths, after expiry, or once its playback session has ended. Raises when no secret is configured: an
    asset that requires signing must never be handed out unsigned."""
    if not secret:
        raise ValueError("media signing secret is not configured")
    parts = urlsplit(url)
    exp = int(time.time()) + ttl_s
    params = {"exp": exp, "sig": _media_sig(secret, parts.path, exp, sid)}
    if sid:
        params["sid"] = sid
    q = (parts.query + "&" if parts.query else "") + urlencode(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, q, parts.fragment))


def verify_media_signature(secret: str, path: str, exp: int, sid: str, sig: str, now: float | None = None) -> bool:
    if not secret or exp <= (now if now is not None else time.time()):
        return False
    return safe_eq(_media_sig(secret, path, exp, sid), sig)


def validate_password_strength(pw: str) -> str | None:
    if len(pw) < 10:
        return "Password must be at least 10 characters."
    if len(pw) > 128:
        return "Password must be at most 128 characters."
    if pw.lower() in _COMMON or len(set(pw)) < 4:
        return "Password is too common."
    return None
