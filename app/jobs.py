"""Scheduled jobs: python -m app.jobs release_notify   (hourly from cron or a scheduler).  `notify` does everything `release_notify` does and more."""
import logging
import sys

from .db import SessionLocal
from .services.notify import notify_all, notify_released

log = logging.getLogger("ott.jobs")


def release_notify() -> int:
    with SessionLocal() as db:
        n = notify_released(db)
    log.info("release_notify: %s notifications", n)
    return n


def notify() -> dict:
    """Everything the bell can announce, for every profile: released reminders, new episodes, titles now playable."""
    with SessionLocal() as db:
        out = notify_all(db)
    log.info("notify: %s", out)
    return out


JOBS = {"release_notify": release_notify, "notify": notify}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) != 2 or sys.argv[1] not in JOBS:
        sys.exit(f"usage: python -m app.jobs [{'|'.join(JOBS)}]")
    print(JOBS[sys.argv[1]]())
