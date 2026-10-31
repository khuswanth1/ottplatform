"""Two-level cache (process memory + optional Redis) with single-flight loading and stale-if-error."""
import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

from .config import get_settings

_MAX_MEM = 5000
log = logging.getLogger("ott.cache")


@dataclass
class Loaded:
    """Return from a loader to also store an HTTP ETag next to the value."""
    value: Any
    etag: str | None = None


@dataclass
class Entry:
    value: Any
    fresh_until: float
    stale_until: float
    etag: str | None = None


class Cache:
    def __init__(self):
        self._mem: OrderedDict[str, Entry] = OrderedDict()
        self._lock = threading.Lock()
        self._flight: dict[str, threading.Lock] = {}
        self._redis = None
        self._retry_at = 0.0  # when to try connecting again after a failure
        self._connect()

    def _connect(self) -> None:
        url = get_settings().redis_url
        if not url:
            return
        try:
            import redis

            r = redis.Redis.from_url(url, socket_timeout=0.2, socket_connect_timeout=0.2)
            r.ping()
            self._redis = r
            log.info("redis connected")
        except Exception as e:
            self._redis = None
            self._retry_at = time.time() + 5
            log.error("redis unavailable (%s): shared caching and distributed rate limits are degraded", type(e).__name__)

    def redis(self):
        """The live Redis client, reconnecting (at most every 5 s) after an outage; None when not configured/unreachable."""
        if self._redis is None and get_settings().redis_url and time.time() >= self._retry_at:
            with self._lock:
                if self._redis is None and time.time() >= self._retry_at:
                    self._connect()
        return self._redis

    def mark_redis_down(self) -> None:
        if self._redis is not None:
            log.error("redis connection lost: shared caching and distributed rate limits are degraded")
        self._redis = None
        self._retry_at = time.time() + 5

    def get_entry(self, key: str) -> Entry | None:
        with self._lock:
            e = self._mem.get(key)
            if e:
                self._mem.move_to_end(key)
        if e and e.stale_until > time.time():
            return e
        if self.redis():
            try:
                raw = self._redis.get("c:" + key)
                if raw:
                    d = json.loads(raw)
                    e = Entry(d["v"], d["f"], d["s"], d.get("e"))
                    if e.stale_until > time.time():
                        with self._lock:
                            self._mem[key] = e
                        return e
            except Exception:
                self.mark_redis_down()
        return None

    def set(self, key: str, value: Any, ttl: int, grace: int = 0, etag: str | None = None) -> None:
        t = time.time()
        e = Entry(value, t + ttl, t + ttl + grace, etag)
        with self._lock:
            self._mem[key] = e
            self._mem.move_to_end(key)
            while len(self._mem) > _MAX_MEM:
                self._mem.popitem(last=False)
        if self.redis():
            try:
                payload = json.dumps({"v": value, "f": e.fresh_until, "s": e.stale_until, "e": etag})
                self._redis.set("c:" + key, payload, ex=max(1, ttl + grace))
            except Exception:
                self.mark_redis_down()

    def delete(self, key: str) -> None:
        with self._lock:
            self._mem.pop(key, None)
        if self.redis():
            try:
                self._redis.delete("c:" + key)
            except Exception:
                self.mark_redis_down()

    def clear(self) -> None:
        with self._lock:
            self._mem.clear()

    def get_or_load(self, key: str, ttl: int, loader: Callable[[], Any], grace: int | None = None):
        """Returns (value, state): state is 'hit', 'miss' or 'stale'. Concurrent misses share one load."""
        grace = get_settings().stale_grace if grace is None else grace
        e = self.get_entry(key)
        if e and e.fresh_until > time.time():
            return e.value, "hit"
        with self._lock:
            flight = self._flight.setdefault(key, threading.Lock())
        with flight:
            e = self.get_entry(key)  # another thread may have filled it while we waited
            if e and e.fresh_until > time.time():
                return e.value, "hit"
            try:
                value = loader()
            except Exception:
                if e:  # provider failed -> serve stale data rather than an error
                    return e.value, "stale"
                raise
            etag = None
            if isinstance(value, Loaded):
                value, etag = value.value, value.etag
            self.set(key, value, ttl, grace, etag)
            return value, "miss"

    def ping(self) -> bool:
        """True when Redis is not configured (nothing to be down) or answers; False when configured but unreachable."""
        if not get_settings().redis_url:
            return True
        r = self.redis()
        if not r:
            return False
        try:
            return bool(r.ping())
        except Exception:
            self.mark_redis_down()
            return False


cache = Cache()
