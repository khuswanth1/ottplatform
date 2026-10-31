"""Background scheduler: python -m app.worker

Runs the periodic jobs outside the API process so request handlers never do long work: bell notifications (hourly) and
data retention (daily). A Redis lock keeps two replicas from running the same job at the same time; without Redis a single
worker is assumed. SIGTERM/SIGINT finish the job in flight and exit, so `docker stop` never cuts a job in half. Each job's
outcome is logged and counted (metrics are per process; scrape the API for request metrics, read worker logs for jobs)."""
import logging
import signal
import threading
import time

from . import metrics, retention
from .cache import cache
from .db import SessionLocal
from .jobs import notify

log = logging.getLogger("ott.worker")
_stop = threading.Event()

def expire_prepaid() -> int:
    from .routers.billing import expire_prepaid as run  # lazy: the router module pulls in the whole API

    with SessionLocal() as db:
        return run(db)


# name -> (function, every N seconds)
SCHEDULE = {"notify": (notify, 3600), "retention": (retention.run, 86400), "expire_prepaid": (expire_prepaid, 300)}


def _claim(name: str, every_s: int) -> bool:
    """True when this process may run `name` now. Redis SET NX EX makes the claim atomic across replicas."""
    r = cache.redis()
    if r is None:
        return True
    try:
        return bool(r.set(f"job:{name}", "1", nx=True, ex=max(60, every_s - 60)))
    except Exception:
        cache.mark_redis_down()
        return True  # Redis is down: run rather than miss the job (jobs are idempotent)


def run_job(name: str, fn) -> bool:
    t0 = time.perf_counter()
    try:
        fn()
    except Exception:
        metrics.inc("worker_job_failures_total", job=name)
        log.exception("job %s failed", name)
        return False
    metrics.inc("worker_job_runs_total", job=name)
    log.info("job %s ok in %.1fs", name, time.perf_counter() - t0)
    return True


def loop(tick_s: float = 30.0, schedule: dict | None = None) -> None:
    schedule = schedule or SCHEDULE
    due = {name: 0.0 for name in schedule}  # everything is due on start-up
    while not _stop.is_set():
        now = time.monotonic()
        for name, (fn, every_s) in schedule.items():
            if _stop.is_set():
                break
            if due[name] <= now and _claim(name, every_s):
                run_job(name, fn)
                due[name] = time.monotonic() + every_s
            elif due[name] <= now:
                due[name] = now + every_s  # another replica ran it
        _stop.wait(tick_s)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: _stop.set())
    log.info("worker started: %s", ", ".join(f"{n} every {e}s" for n, (_, e) in SCHEDULE.items()))
    loop()
    log.info("worker stopped")


if __name__ == "__main__":
    main()
