"""Notifications for the bell. Three kinds:

  reminder_released  a title the profile asked to be reminded about is now out
  new_episode        a title on the profile's list or in its history has an episode that aired in the last 14 days
  new_in_list        a title on the profile's list became playable here after it was added

All of it runs from the hourly job (`python -m app.jobs notify`) and, so nothing depends on cron in small setups, when a
profile opens its notification list (the two content scans at most once every 10 minutes per profile)."""
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..cache import cache
from ..maturity import title_allowed
from ..models import (
    Episode, MediaAsset, Notification, Profile, Reminder, Season, Title, TitleRight, WatchlistItem, WatchProgress,
)

EPISODE_WINDOW_DAYS = 14
SCAN_TTL_S = 600


def notify_released(db: Session, profile_id: uuid.UUID | None = None) -> int:
    """For each reminder whose title now has a release date on or before today (UTC), create one notification and mark the
    reminder as done. Safe to run twice at once: the unique key stops a duplicate notification. Returns how many were made.
    A viewer in another time zone may see it up to a day early or late (release dates carry no time)."""
    now = datetime.now(timezone.utc)
    stmt = (select(Reminder).join(Title, Title.id == Reminder.title_id)
            .where(Reminder.notified_at.is_(None), Title.status == "published", Title.release_date <= now.date()))
    if profile_id:
        stmt = stmt.where(Reminder.profile_id == profile_id)
    made = 0
    for r in db.scalars(stmt).all():
        exists = db.scalar(select(Notification.id).where(Notification.profile_id == r.profile_id,
                                                         Notification.kind == "reminder_released", Notification.title_id == r.title_id))
        if not exists:
            db.add(Notification(profile_id=r.profile_id, kind="reminder_released", title_id=r.title_id))
            made += 1
        r.notified_at = now
    db.commit()
    return made


def _newest_episodes(db: Session, today: date) -> dict[uuid.UUID, Episode]:
    """For every published series, its most recently aired episode inside the window (if any)."""
    since = today - timedelta(days=EPISODE_WINDOW_DAYS)
    rows = db.execute(select(Episode, Season.number).join(Season, Season.id == Episode.season_id)
                      .join(Title, Title.id == Episode.title_id)
                      .where(Title.status == "published", Title.type == "series", Episode.air_date >= since, Episode.air_date <= today)).all()
    best: dict[uuid.UUID, tuple[tuple, Episode]] = {}
    for ep, season_no in rows:
        key = (ep.air_date, season_no, ep.number)
        if ep.title_id not in best or key > best[ep.title_id][0]:
            best[ep.title_id] = (key, ep)
    return {tid: ep for tid, (_, ep) in best.items()}


def notify_new_episodes(db: Session, profile_id: uuid.UUID | None = None) -> int:
    """One notification per (profile, title) for the newest aired episode, so a series released all at once is one
    notification, not eight. Interest means the title is on the profile's list (added no later than the air date) or the
    profile has watched something of it earlier than the new episode."""
    today = datetime.now(timezone.utc).date()
    newest = _newest_episodes(db, today)
    if not newest:
        return 0
    interest: dict[tuple[uuid.UUID, uuid.UUID], dict] = {}
    lists = select(WatchlistItem.profile_id, WatchlistItem.title_id, func.min(WatchlistItem.added_at)).where(
        WatchlistItem.title_id.in_(newest)).group_by(WatchlistItem.profile_id, WatchlistItem.title_id)
    if profile_id:
        lists = lists.where(WatchlistItem.profile_id == profile_id)
    for pid, tid, added in db.execute(lists):
        interest[(pid, tid)] = {"added": added.date() if added else None, "watched_until": None, "watched_ids": set()}
    seen = select(WatchProgress.profile_id, WatchProgress.title_id, WatchProgress.episode_id, Episode.air_date).join(
        Episode, Episode.id == WatchProgress.episode_id).where(WatchProgress.title_id.in_(newest), WatchProgress.hidden_at.is_(None))
    if profile_id:
        seen = seen.where(WatchProgress.profile_id == profile_id)
    for pid, tid, eid, aired in db.execute(seen):
        i = interest.setdefault((pid, tid), {"added": None, "watched_until": None, "watched_ids": set()})
        i["watched_ids"].add(eid)
        if aired and (i["watched_until"] is None or aired > i["watched_until"]):
            i["watched_until"] = aired
    if not interest:
        return 0
    profiles = {p.id: p for p in db.scalars(select(Profile).where(Profile.id.in_({pid for pid, _ in interest})))}
    titles = {t.id: t for t in db.scalars(select(Title).where(Title.id.in_(newest)))}
    made = 0
    for (pid, tid), i in interest.items():
        ep, prof, title = newest[tid], profiles.get(pid), titles.get(tid)
        if not prof or not title or not title_allowed(title, prof.maturity_level) or ep.id in i["watched_ids"]:
            continue
        on_list = i["added"] is not None and i["added"] <= ep.air_date
        caught_up = i["watched_ids"] and (i["watched_until"] is None or i["watched_until"] < ep.air_date)
        if not (on_list or caught_up):
            continue
        already = db.scalar(select(Notification.id).join(Episode, Episode.id == Notification.episode_id).where(
            Notification.profile_id == pid, Notification.kind == "new_episode", Notification.title_id == tid,
            Episode.air_date >= ep.air_date).limit(1))
        if already:
            continue
        db.add(Notification(profile_id=pid, kind="new_episode", title_id=tid, episode_id=ep.id, episode_key=str(ep.id)))
        made += 1
    db.commit()
    return made


def notify_now_playable(db: Session, profile_id: uuid.UUID | None = None) -> int:
    """A title on the profile's list that got a verified right and an active source after the profile added it. Ignores
    territories (the title page still says where it can be played), so it can promise slightly more than a viewer gets."""
    now = datetime.now(timezone.utc)
    stmt = (select(WatchlistItem.profile_id, WatchlistItem.title_id).join(Title, Title.id == WatchlistItem.title_id)
            .join(TitleRight, TitleRight.title_id == Title.id).join(MediaAsset, MediaAsset.title_id == Title.id)
            .where(Title.status == "published", TitleRight.status == "verified",
                   or_(TitleRight.starts_at.is_(None), TitleRight.starts_at <= now),
                   or_(TitleRight.expires_at.is_(None), TitleRight.expires_at > now),
                   MediaAsset.is_active.is_(True), MediaAsset.created_at >= WatchlistItem.added_at).distinct())
    if profile_id:
        stmt = stmt.where(WatchlistItem.profile_id == profile_id)
    pairs = db.execute(stmt).all()
    profiles = {p.id: p for p in db.scalars(select(Profile).where(Profile.id.in_({p for p, _ in pairs})))} if pairs else {}
    titles = {t.id: t for t in db.scalars(select(Title).where(Title.id.in_({t for _, t in pairs})))} if pairs else {}
    made = 0
    for pid, tid in pairs:
        prof, title = profiles.get(pid), titles.get(tid)
        if not prof or not title_allowed(title, prof.maturity_level):
            continue
        if db.scalar(select(Notification.id).where(Notification.profile_id == pid, Notification.kind == "new_in_list",
                                                   Notification.title_id == tid)):
            continue
        db.add(Notification(profile_id=pid, kind="new_in_list", title_id=tid))
        made += 1
    db.commit()
    return made


def notify_all(db: Session, profile_id: uuid.UUID | None = None) -> dict[str, int]:
    return {"released": notify_released(db, profile_id), "episodes": notify_new_episodes(db, profile_id),
            "playable": notify_now_playable(db, profile_id)}


def notify_profile_throttled(db: Session, profile_id: uuid.UUID) -> None:
    """What the bell calls: reminders every time (one cheap query), the two content scans at most every 10 minutes."""
    notify_released(db, profile_id)

    def scan() -> bool:
        notify_new_episodes(db, profile_id)
        notify_now_playable(db, profile_id)
        return True

    cache.get_or_load(f"notify-scan:{profile_id}", SCAN_TTL_S, scan)
