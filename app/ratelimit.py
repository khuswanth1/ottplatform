import logging
import threading
import time

from fastapi import HTTPException, Request

from . import metrics
from .cache import cache
from .config import get_settings

log = logging.getLogger("ott.ratelimit")

_lock = threading.Lock()
_counters: dict[str, tuple[int, float]] = {}


def client_ip(request: Request) -> str:
    if get_settings().trust_proxy:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[-1].strip()  # rightmost = appended by our trusted proxy
    return request.client.host if request.client else "unknown"


def _hit(key: str, window: int) -> int:
    """Shared (Redis) counter so every worker and replica sees the same count. If Redis is configured but unreachable the
    process-local counter is used for that call only: limits become per-worker (looser, never absent), the outage is logged
    and counted, and Redis is retried on the next request instead of being switched off for the life of the process."""
    r = cache.redis()
    if r:
        try:
            pipe = r.pipeline()
            pipe.incr("rl:" + key)
            pipe.expire("rl:" + key, window, nx=True)
            return int(pipe.execute()[0])
        except Exception:
            cache.mark_redis_down()
    if get_settings().redis_url:
        metrics.inc("ratelimit_degraded_total")
    now = time.time()
    with _lock:
        count, reset = _counters.get(key, (0, now + window))
        if reset <= now:
            count, reset = 0, now + window
        count += 1
        _counters[key] = (count, reset)
        if len(_counters) > 50000:
            for k in [k for k, (_, r2) in _counters.items() if r2 <= now]:
                _counters.pop(k, None)
        return count


def reset_limits() -> None:
    with _lock:
        _counters.clear()


def rate_limit(scope: str, limit: int, window_s: int = 60):
    """FastAPI dependency factory: fixed window per client IP."""

    def dep(request: Request):
        if get_settings().env == "test" and not getattr(request.app.state, "enforce_limits", False):
            return
        if _hit(f"{scope}:{client_ip(request)}", window_s) > limit:
            raise HTTPException(429, "Too many requests. Please slow down.", headers={"Retry-After": str(window_s)})

    return dep


def limit_key(scope: str, ident: str, limit: int, window_s: int) -> None:
    if _hit(f"{scope}:{ident}", window_s) > limit:
        raise HTTPException(429, "Too many attempts. Try again later.", headers={"Retry-After": str(window_s)})
