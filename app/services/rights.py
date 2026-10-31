"""Pure rights evaluation - the single gate every playback request passes through."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

_KIND_ORDER = {"hls": 0, "dash": 1, "mp4": 2, "embed": 3}
# lower = more specific reason; used to explain the *closest* failing right to the caller
_PRIORITY = ["entitlement_required", "territory_blocked", "expired", "not_started", "not_verified"]


@dataclass
class Decision:
    allowed: bool
    code: str  # ok | no_rights | not_verified | expired | not_started | territory_blocked | entitlement_required
    message: str
    right: object | None = None


_MESSAGES = {
    "no_rights": "No playback rights are on file for this title.",
    "not_verified": "Rights for this title have not been verified yet.",
    "expired": "The license for this title has expired.",
    "not_started": "This title is not yet available.",
    "territory_blocked": "This title is not licensed for your country.",
    "entitlement_required": "A premium plan is required to watch this title.",
}


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def evaluate_rights(rights: Iterable, now: datetime, country: str | None, plan: str, is_admin: bool = False) -> Decision:
    rights = list(rights)
    if not rights:
        return Decision(False, "no_rights", _MESSAGES["no_rights"])
    failures: list[str] = []
    for r in rights:
        if r.status != "verified":
            failures.append("not_verified")
            continue
        if r.starts_at and _aware(r.starts_at) > now:
            failures.append("not_started")
            continue
        if r.expires_at and _aware(r.expires_at) <= now:
            failures.append("expired")
            continue
        terr = [t.upper() for t in (r.territories or [])]
        if "*" not in terr and (not country or country.upper() not in terr):
            failures.append("territory_blocked")
            continue
        if r.entitlement == "premium" and plan != "premium" and not is_admin:
            failures.append("entitlement_required")
            continue
        return Decision(True, "ok", "Playback permitted.", r)
    code = min(failures, key=_PRIORITY.index)
    return Decision(False, code, _MESSAGES[code])


def pick_asset(assets: Iterable):
    active = [a for a in assets if a.is_active]
    return min(active, key=lambda a: _KIND_ORDER.get(a.kind, 9), default=None)
