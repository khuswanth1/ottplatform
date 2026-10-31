"""Retention job: python -m app.retention   (run daily from cron / a scheduler)."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_

from .config import get_settings
from .db import SessionLocal
from .models import Notification, AuditLog, AuthSession, EmailToken, PlaybackSession, TitleAvailability, AvailabilityFetch

log = logging.getLogger("ott.retention")


def run() -> dict[str, int]:
    s, now = get_settings(), datetime.now(timezone.utc)
    out = {}
    with SessionLocal() as db:
        jobs = {
            "sessions": delete(AuthSession).where(or_(AuthSession.expires_at < now - timedelta(days=7),
                                                      AuthSession.revoked_at < now - timedelta(days=7))),
            "email_tokens": delete(EmailToken).where(EmailToken.expires_at < now - timedelta(days=7)),
            "playback_sessions": delete(PlaybackSession).where(
                PlaybackSession.issued_at < now - timedelta(days=s.retain_playback_sessions_days)),
            "audit_logs": delete(AuditLog).where(AuditLog.created_at < now - timedelta(days=s.retain_audit_days)),
            # availability rows older than 30 days belong to titles nobody looked at; they refetch on demand
            "availability_fetches": delete(AvailabilityFetch).where(AvailabilityFetch.fetched_at < now - timedelta(days=30)),
        }
        jobs["notifications"] = delete(Notification).where(Notification.created_at < now - timedelta(days=90))
        for name, stmt in jobs.items():
            out[name] = db.execute(stmt).rowcount
        # orphaned availability rows (no matching fetch marker)
        db.commit()
    log.info("retention: %s", out)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run())
