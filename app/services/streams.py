"""Concurrent stream limits. A stream counts while its playback session is open (not ended, not expired) and the player
has checked in within LEASE_TTL_S. The player sends a heartbeat every 30 s, so a closed tab or a lost connection frees its
slot after at most 90 s. The limit is per account (all profiles), from the live subscription's plan, else the free plan."""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from ..models import PlaybackSession, Plan, Subscription, User

LEASE_TTL_S = 90
HEARTBEAT_S = 30
LIVE_STATUSES = ("trialing", "active", "past_due")


def stream_limit(db: Session, user: User) -> int:
    """How many screens at once this account may use. Falls back to 1 if the plan rows are missing."""
    plan = db.scalar(select(Plan).join(Subscription, Subscription.plan_id == Plan.id)
                     .where(Subscription.user_id == user.id, Subscription.status.in_(LIVE_STATUSES)).limit(1))
    if not plan:
        plan = db.scalar(select(Plan).where(Plan.code == "free"))
    return max(1, plan.max_streams) if plan else 1


def lock_account(db: Session, user_id: uuid.UUID) -> None:
    """Serialise limit checks for one account, so two devices starting at once cannot both pass. PostgreSQL only; SQLite
    (tests, quick local runs) has a single writer anyway."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("select pg_advisory_xact_lock(hashtext(:k))"), {"k": str(user_id)})


def _live(user_id: uuid.UUID, now: datetime):
    return (PlaybackSession.user_id == user_id, PlaybackSession.ended_at.is_(None), PlaybackSession.expires_at > now,
            PlaybackSession.last_seen_at >= now - timedelta(seconds=LEASE_TTL_S))


def live_streams(db: Session, user_id: uuid.UUID, now: datetime, exclude: uuid.UUID | None = None) -> int:
    stmt = select(func.count()).select_from(PlaybackSession).where(*_live(user_id, now))
    if exclude:
        stmt = stmt.where(PlaybackSession.id != exclude)
    return db.scalar(stmt) or 0


def replace_same_item(db: Session, user_id: uuid.UUID, profile_id: uuid.UUID, title_id: uuid.UUID,
                      episode_id: uuid.UUID | None, now: datetime) -> None:
    """Reloading the page or re-opening the same episode on the same profile replaces its own earlier stream instead of
    counting twice (the old tab's cleanup request may not have arrived)."""
    db.execute(update(PlaybackSession).where(
        *_live(user_id, now), PlaybackSession.profile_id == profile_id, PlaybackSession.title_id == title_id,
        PlaybackSession.episode_id.is_not_distinct_from(episode_id)).values(ended_at=now))
