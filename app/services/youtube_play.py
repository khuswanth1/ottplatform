"""Attach a YouTube embed to a title or episode the first time someone presses Play."""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Episode, MediaAsset, Season, Title, TitleRight
from ..providers.base import ProviderError
from ..providers.registry import get_registry

log = logging.getLogger("ott.youtube")


def youtube_enabled() -> bool:
    yt = get_registry().youtube
    return bool(yt and yt.configured())


def has_asset(db: Session, title_id: uuid.UUID, episode_id: uuid.UUID | None) -> bool:
    return db.scalar(select(MediaAsset.id).where(
        MediaAsset.title_id == title_id, MediaAsset.is_active.is_(True),
        MediaAsset.episode_id == episode_id).limit(1)) is not None


def ensure_youtube_asset(db: Session, t: Title, ep: Episode | None, country: str | None = None) -> bool:
    """True when the title/episode now has a source. Does nothing if one exists or YouTube is not configured or
    nothing on YouTube's licensed Movies/Shows catalogue matches strictly."""
    if has_asset(db, t.id, ep.id if ep else None):
        return True
    yt = get_registry().youtube
    if not (yt and yt.configured()):
        return False
    try:
        if ep:
            season = db.get(Season, ep.season_id)
            m = yt.find_episode(t.name, season.number if season else 1, ep.number, ep.name,
                                ep.runtime_minutes or t.runtime_minutes, country)
        else:
            m = yt.find_movie(t.name, t.year, t.runtime_minutes, country)
    except ProviderError as e:
        log.warning("youtube lookup failed for %s: %s", t.name, e)
        return False
    if not m:
        return False
    if not db.scalar(select(TitleRight.id).where(TitleRight.title_id == t.id).limit(1)):
        db.add(TitleRight(
            title_id=t.id, status="verified", license_type="licensed", entitlement="registered", source="youtube",
            territories=(m.allowed_regions or ["*"]) if not ep else ["*"],
            evidence_url=m.watch_url,
            notes=f"Matched on YouTube's licensed catalogue and embeddable by its owner: \"{m.title}\" ({m.channel}). "
                  "Matched by title and length, not checked by a person."))
    db.add(MediaAsset(title_id=t.id, episode_id=ep.id if ep else None, kind="embed", url=m.embed_url,
                      is_active=True))
    db.commit()
    return True
