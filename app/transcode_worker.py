"""Video processing worker: python -m app.transcode_worker

Polls the media_jobs queue and runs one job at a time (ffmpeg uses every core already). Scale out by running more
containers: claims use SELECT ... FOR UPDATE SKIP LOCKED on PostgreSQL. On SIGTERM it finishes the job in flight, then exits,
so give the container a long stop_grace_period (a stopped-mid-job worker is also safe: the job is reclaimed after the lease)."""
import logging
import signal
import threading

from .db import SessionLocal
from .services import transcode

log = logging.getLogger("ott.transcode.worker")
_stop = threading.Event()


def run_once(worker_id: str, run=transcode.run_command) -> bool:
    """Claim and process one job. True if there was one."""
    with SessionLocal() as db:
        job = transcode.claim_next(db, worker_id)
        if not job:
            return False
        transcode.process(db, job, run)
        return True


def loop(poll_s: float = 5.0) -> None:
    wid = transcode.worker_id()
    while not _stop.is_set():
        try:
            busy = run_once(wid)
        except Exception:
            log.exception("worker iteration failed")  # e.g. database briefly unreachable: back off and keep going
            busy = False
        if not busy:
            _stop.wait(poll_s)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: _stop.set())
    log.info("transcode worker started as %s", transcode.worker_id())
    loop()
    log.info("transcode worker stopped")


if __name__ == "__main__":
    main()
