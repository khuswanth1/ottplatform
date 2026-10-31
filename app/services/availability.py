import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AvailabilityFetch, MediaAsset, Title, TitleAvailability, TitleRight
from ..providers.base import ProviderError
from ..providers.registry import get_registry
from ..schemas import AvailabilityOut, DirectAccess, ExternalOption
from .catalog import direct_access, title_ext
from .rights import evaluate_rights

LABELS = {"free": "Free (external)", "subscription": "Subscription", "rent": "Rent", "buy": "Buy"}
_locks: dict[tuple, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: tuple) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def refresh(db: Session, t: Title, country: str) -> bool:
    """Returns True when data is fresh (or just refreshed); False when every provider failed (stale data served)."""
    ttl = timedelta(seconds=get_settings().ttl_availability)
    now = datetime.now(timezone.utc)

    def fresh() -> bool:
        f = db.get(AvailabilityFetch, (t.id, country))
        return bool(f and (f.fetched_at if f.fetched_at.tzinfo else f.fetched_at.replace(tzinfo=timezone.utc)) > now - ttl)

    if fresh():
        return True
    with _lock_for((t.id, country)):  # concurrent viewers trigger one provider call
        db.expire_all()
        if fresh():
            return True
        ext = title_ext(t)
        rows, ok = [], False
        for p in get_registry().availability:
            if not p.configured():
                continue
            try:
                got = p.availability(ext, t.type, country)
            except ProviderError:
                continue
            ok = True
            if got:
                rows = got
                break
        if not ok:
            return False
        db.execute(delete(TitleAvailability).where(TitleAvailability.title_id == t.id, TitleAvailability.country == country))
        for r in rows:
            db.add(TitleAvailability(title_id=t.id, country=country, source=r.source, provider_name=r.provider_name,
                                     kind=r.kind, web_url=r.web_url, price=r.price, format=r.format))
        f = db.get(AvailabilityFetch, (t.id, country))
        if f:
            f.fetched_at = now
        else:
            db.add(AvailabilityFetch(title_id=t.id, country=country, fetched_at=now))
        db.commit()
        return True


def build_availability(db: Session, t: Title, country: str, plan: str, is_admin: bool,
                       rights_country: str | None = None) -> AvailabilityOut:
    """`country` selects which region's external provider list is shown (display only). Direct playback is
    always evaluated against `rights_country`, the trusted viewer location, never the display choice."""
    rights_country = rights_country or country
    ok = refresh(db, t, country)
    rows = db.scalars(select(TitleAvailability).where(
        TitleAvailability.title_id == t.id, TitleAvailability.country == country)).all()
    order = {"free": 0, "subscription": 1, "rent": 2, "buy": 3}
    external = sorted((ExternalOption(provider=r.provider_name, kind=r.kind, label=LABELS[r.kind], web_url=r.web_url,
                                      price=r.price, format=r.format) for r in rows),
                      key=lambda o: (order[o.kind], o.provider))
    access = direct_access(db, [t.id], rights_country)
    direct, reason = None, None
    if t.id in access:
        ent = access[t.id]
        direct = DirectAccess(entitlement=ent, label="Free to watch here" if ent == "registered" else "Premium")
    else:
        rights = db.scalars(select(TitleRight).where(TitleRight.title_id == t.id)).all()
        has_asset = db.scalar(select(MediaAsset.id).where(MediaAsset.title_id == t.id, MediaAsset.is_active.is_(True)).limit(1))
        if rights and has_asset:
            reason = evaluate_rights(rights, datetime.now(timezone.utc), rights_country, plan, is_admin).message
    attribution = []
    if any(r.source == "watchmode" for r in rows):
        attribution.append("Streaming availability data by Watchmode.")
    if any(r.source == "tmdb" for r in rows):
        attribution.append("Streaming availability data provided by JustWatch.")
    return AvailabilityOut(country=country, viewer_country=rights_country, direct=direct, direct_unavailable_reason=reason, external=external,
                           degraded=not ok, attribution=attribution)
