import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import metrics
from ..config import get_settings
from ..db import get_db
from ..deps import _profile_for, get_optional_user, get_profile, require_verified, resolve_country
from ..maturity import blocked
from ..models import Episode, MediaAsset, MediaJob, PlaybackSession, Profile, Season, Title, TitleRight, User, WatchProgress
from ..ratelimit import rate_limit
from ..schemas import Msg, PlaybackIn, PlaybackOut, SubtitleOut
from ..security import sign_media_url, verify_media_signature
from ..services import catalog as svc
from ..services.rights import evaluate_rights, pick_asset
from ..services.youtube_play import ensure_youtube_asset
from ..services.streams import LEASE_TTL_S, lock_account, live_streams, replace_same_item, stream_limit
from .progress import next_episode, previous_episode

router = APIRouter(prefix="/playback", tags=["playback"])


def host_allowed(url: str, allowed: list[str]) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == a or host.endswith("." + a) for a in allowed)


def url_conflict(db: Session, url: str, title_id: uuid.UUID, episode_id: uuid.UUID | None,
                 exclude_id: uuid.UUID | None = None) -> bool:
    """True if another active asset with this exact URL is attached to a different title or episode.
    One stream must belong to exactly one title/episode; a shared URL means someone's content would be
    played under another title's name."""
    stmt = select(MediaAsset.id).where(
        MediaAsset.url == url, MediaAsset.is_active.is_(True),
        (MediaAsset.title_id != title_id)
        | (MediaAsset.episode_id.is_distinct_from(episode_id)))
    if exclude_id:
        stmt = stmt.where(MediaAsset.id != exclude_id)
    return db.scalar(stmt.limit(1)) is not None


def default_episode(db: Session, t: Title, profile: Profile) -> Episode | None:
    """Play pressed on a series: carry on where this profile stopped, else start at season 1 episode 1."""
    prog = db.scalar(select(WatchProgress).where(
        WatchProgress.profile_id == profile.id, WatchProgress.title_id == t.id, WatchProgress.completed.is_(False),
        WatchProgress.episode_id.is_not(None)).order_by(WatchProgress.updated_at.desc()).limit(1))
    if prog and (ep := db.get(Episode, prog.episode_id)):
        return ep
    seasons = db.scalars(select(Season).where(Season.title_id == t.id, Season.number > 0).order_by(Season.number)).all()
    if not seasons:
        svc.ensure_details(db, t)
        seasons = db.scalars(select(Season).where(Season.title_id == t.id, Season.number > 0).order_by(Season.number)).all()
    for season in seasons[:3]:
        svc.ensure_episodes(db, t, season, profile.language or "en")
        ep = db.scalar(select(Episode).where(Episode.season_id == season.id).order_by(Episode.number).limit(1))
        if ep:
            return ep
    return None


def _limit_message(limit: int) -> str:
    screens = "1 screen" if limit == 1 else f"{limit} screens"
    return f"Your plan allows {screens} at a time and all of them are in use. Stop playback on another device, or choose a plan with more screens."


def _deny(status: int, code: str, message: str, title_id: uuid.UUID):
    return HTTPException(status, detail={
        "code": code, "message": message,
        "alternatives": f"/api/v1/titles/{title_id}/availability",  # authorized external providers, if any
    })


def _authorized_asset(db: Session, t: Title, ep: Episode | None, user: User, country: str, now: datetime) -> MediaAsset:
    """The single gate for handing out a source: rights, entitlement, territory, one-title-per-URL and host allow-list."""
    s = get_settings()
    ensure_youtube_asset(db, t, ep, country)  # first Play of this title/episode: look it up on YouTube's licensed catalogue
    svc.ensure_playback_assets(db, t, ep)
    rights = db.scalars(select(TitleRight).where(TitleRight.title_id == t.id)).all()
    decision = evaluate_rights(rights, now, country, user.plan, user.role == "admin")
    if not decision.allowed:
        metrics.inc("playback_denied_total", code=decision.code)
        raise _deny(403, decision.code, decision.message, t.id)

    assets = db.scalars(select(MediaAsset).where(
        MediaAsset.title_id == t.id, MediaAsset.is_active.is_(True),
        MediaAsset.episode_id == (ep.id if ep else None))).all()
    asset = pick_asset(assets)
    if not asset:
        raise _deny(404, "no_authorized_source", "No authorized source is available on this platform.", t.id)
    if url_conflict(db, asset.url, t.id, ep.id if ep else None, exclude_id=asset.id):
        metrics.inc("playback_denied_total", code="source_conflict")
        raise _deny(409, "source_conflict",
                    "This source is attached to more than one title, so it was blocked instead of risking the wrong video.", t.id)
    if asset.kind == "embed" and not host_allowed(asset.url, s.embed_allowed_hosts):
        metrics.inc("playback_denied_total", code="embed_host_not_allowed")
        raise _deny(403, "embed_host_not_allowed", "This source is not on the approved host list.", t.id)
    return asset


def _delivery_url(asset: MediaAsset, session_id: uuid.UUID | None) -> str:
    """Signed when the asset demands it. Fails closed (503) when signing is required but no secret is configured."""
    if not asset.requires_signing:
        return asset.url
    s = get_settings()
    try:
        return sign_media_url(asset.url, s.cdn_signing_secret, s.cdn_signing_ttl_s, str(session_id) if session_id else "")
    except ValueError:
        metrics.inc("playback_denied_total", code="signing_unavailable")
        raise HTTPException(503, {"code": "signing_unavailable", "message": "Secure delivery is not configured for this title."})


@router.post("/sessions", response_model=PlaybackOut, status_code=201,
             dependencies=[Depends(rate_limit("playback", 30, 60))])
def create_session(body: PlaybackIn, request: Request, user: User = Depends(require_verified),
                   profile: Profile = Depends(get_profile), db: Session = Depends(get_db)):
    s = get_settings()
    t = db.get(Title, body.title_id)
    if not t or t.status != "published":
        raise HTTPException(404, "Title not found.")
    if blocked(profile, t):
        if profile.is_kids:
            raise _deny(403, "kids_restricted", "This title is not available on a kids profile.", t.id)
        raise _deny(403, "maturity_restricted", "This title is above this profile's maturity level.", t.id)
    ep = None
    if t.type == "series":
        ep = db.get(Episode, body.episode_id) if body.episode_id else default_episode(db, t, profile)
        if not ep or ep.title_id != t.id:
            raise HTTPException(400 if body.episode_id else 404,
                                "A valid episode_id is required for series." if body.episode_id
                                else "No episodes are listed for this series yet.")
    elif body.episode_id:
        raise HTTPException(400, "Movies have no episodes.")

    country, now = resolve_country(request), datetime.now(timezone.utc)
    asset = _authorized_asset(db, t, ep, user, country, now)

    if user.role != "admin":
        lock_account(db, user.id)  # check and insert under one lock so two devices cannot both slip in
        replace_same_item(db, user.id, profile.id, t.id, ep.id if ep else None, now)
        limit = stream_limit(db, user)
        if live_streams(db, user.id, now) >= limit:
            db.rollback()
            metrics.inc("playback_denied_total", code="stream_limit")
            raise _deny(409, "stream_limit", _limit_message(limit), t.id)

    expires = now + timedelta(minutes=s.playback_session_minutes)
    sid = uuid.uuid4()
    url = _delivery_url(asset, sid)  # before the slot is taken: a 503 here must not consume a stream
    ps = PlaybackSession(id=sid, user_id=user.id, profile_id=profile.id, title_id=t.id, episode_id=ep.id if ep else None,
                         asset_id=asset.id, country=country, expires_at=expires, last_seen_at=now)
    db.add(ps)
    db.commit()
    metrics.inc("playback_started_total", kind=asset.kind)

    prog = db.scalar(select(WatchProgress).where(
        WatchProgress.profile_id == profile.id, WatchProgress.title_id == t.id,
        WatchProgress.episode_key == (str(ep.id) if ep else "-")))
    resume = prog.position_seconds if prog and not prog.completed else 0
    nxt = next_episode(db, ep) if ep else None
    prv = previous_episode(db, ep) if ep else None
    return PlaybackOut(
        session_id=ps.id, episode_id=ep.id if ep else None, expires_at=expires, kind=asset.kind, url=url,
        subtitles=[SubtitleOut(**x) for x in (asset.subtitles or [])], audio_languages=asset.audio_languages or [],
        resume_position_seconds=resume, next_episode_id=nxt.id if nxt else None,
        previous_episode_id=prv.id if prv else None, title=svc.cards_from_titles(db, [t], country)[0],
    )


@router.delete("/sessions/{session_id}", response_model=Msg)
def end_session(session_id: uuid.UUID, user: User = Depends(require_verified), db: Session = Depends(get_db)):
    ps = db.scalar(select(PlaybackSession).where(PlaybackSession.id == session_id, PlaybackSession.user_id == user.id))
    if not ps:
        raise HTTPException(404, "Playback session not found.")
    ps.ended_at = ps.ended_at or datetime.now(timezone.utc)
    db.commit()
    return Msg(message="Playback session ended.")


@router.post("/sessions/{session_id}/heartbeat", response_model=Msg,
             dependencies=[Depends(rate_limit("heartbeat", 120, 60))])
def heartbeat(session_id: uuid.UUID, user: User = Depends(require_verified), db: Session = Depends(get_db)):
    """Keeps this stream's slot. Called by the player every 30 s. If the player went quiet long enough for its slot to
    lapse (laptop asleep, bad connection) and the plan's screens are now taken, it gets 409 stream_limit and must stop."""
    now = datetime.now(timezone.utc)
    ps = db.scalar(select(PlaybackSession).where(PlaybackSession.id == session_id, PlaybackSession.user_id == user.id))
    if not ps:
        raise HTTPException(404, "Playback session not found.")
    if ps.ended_at is not None or _aware(ps.expires_at) <= now:
        raise HTTPException(410, {"code": "session_ended", "message": "This playback session has ended."})
    if user.role != "admin" and _aware(ps.last_seen_at) < now - timedelta(seconds=LEASE_TTL_S):
        lock_account(db, user.id)
        limit = stream_limit(db, user)
        if live_streams(db, user.id, now, exclude=ps.id) >= limit:
            ps.ended_at = now
            db.commit()
            metrics.inc("playback_denied_total", code="stream_limit")
            raise HTTPException(409, {"code": "stream_limit", "message": _limit_message(limit)})
    if user.role != "admin":  # licences and plans change mid-stream: stop at the next beat, not at session expiry
        rights = db.scalars(select(TitleRight).where(TitleRight.title_id == ps.title_id)).all()
        decision = evaluate_rights(rights, now, ps.country, user.plan, False)
        if not decision.allowed:
            ps.ended_at = now
            db.commit()
            metrics.inc("playback_denied_total", code=decision.code)
            raise HTTPException(403, {"code": decision.code, "message": decision.message})
    ps.last_seen_at = now
    db.commit()
    return Msg(message="ok")


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/authorize")
def authorize_media(path: str = Query(max_length=1000), exp: int = Query(), sid: str = Query(max_length=36),
                    sig: str = Query(max_length=64), db: Session = Depends(get_db)):
    """Delivery-layer check for signed media. Point nginx `auth_request` / Caddy `forward_auth` at this endpoint (see the
    README) and the edge refuses a segment unless its token is genuine, unexpired, minted for exactly this path, and its
    playback session is still open. 204 = serve, 403 = refuse. Nothing here trusts the browser."""
    try:
        session_id = uuid.UUID(sid)
    except ValueError:
        raise HTTPException(403, "Invalid token.")
    if not verify_media_signature(get_settings().cdn_signing_secret, path, exp, sid, sig):
        metrics.inc("media_authorize_total", result="bad_signature")
        raise HTTPException(403, "Invalid or expired token.")
    ps = db.get(PlaybackSession, session_id)
    if not ps or ps.ended_at is not None or _aware(ps.expires_at) <= datetime.now(timezone.utc):
        metrics.inc("media_authorize_total", result="session_closed")
        raise HTTPException(403, "Playback session is closed.")
    metrics.inc("media_authorize_total", result="ok")
    return Response(status_code=204)


@router.get("/authorize-vod")
def authorize_vod(request: Request, user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    """nginx `auth_request` target for processed video served same-origin under /vod/<job id>/... Every playlist and
    segment request carries the viewer's session cookie, so the check is: signed in, and holding an open playback session
    for the asset that job produced. Playback sessions are only issued after the rights/plan/maturity gate, so media
    bytes follow the same rules as the API; once the session ends or expires, segments stop (403)."""
    original = request.headers.get("x-original-uri", "")
    m = re.match(r"^/vod/([0-9a-fA-F-]{36})/[A-Za-z0-9_.-]+$", original.split("?")[0])
    if not user or not m:
        raise HTTPException(403, "Not allowed.")
    now = datetime.now(timezone.utc)
    ok = db.scalar(select(PlaybackSession.id).join(MediaJob, MediaJob.asset_id == PlaybackSession.asset_id).where(
        MediaJob.id == uuid.UUID(m.group(1)), PlaybackSession.user_id == user.id, PlaybackSession.ended_at.is_(None),
        PlaybackSession.expires_at > now).limit(1))
    if not ok:
        metrics.inc("media_authorize_total", result="vod_denied")
        raise HTTPException(403, "No open playback session for this video.")
    return Response(status_code=204)


@router.get("/{title_id}/download", dependencies=[Depends(rate_limit("download", 20, 60))])
def download_media(title_id: uuid.UUID, request: Request, episode_id: uuid.UUID | None = None,
                   profile_id: str | None = Query(default=None, max_length=36),
                   user: User = Depends(require_verified), db: Session = Depends(get_db)):
    """Redirects to a plain MP4 source after the same checks as playback (sign-in, profile maturity, rights, territory,
    plan). Only MP4 assets are downloadable; streams (HLS/DASH/embeds) are not. The profile comes from the query because a
    link cannot send the X-Profile-Id header."""
    profile = _profile_for(db, user, profile_id or request.headers.get("x-profile-id"), request)
    t = db.get(Title, title_id)
    if not t or t.status != "published" or blocked(profile, t):
        raise HTTPException(404, "Title not found.")
    ep = None
    if t.type == "series":
        ep = db.get(Episode, episode_id) if episode_id else None
        if not ep or ep.title_id != t.id:
            raise HTTPException(400, "A valid episode_id is required for series.")
    elif episode_id:
        raise HTTPException(400, "Movies have no episodes.")
    asset = _authorized_asset(db, t, ep, user, resolve_country(request), datetime.now(timezone.utc))
    if asset.kind != "mp4":
        raise _deny(404, "not_downloadable", "This title is only available to stream.", t.id)
    metrics.inc("download_total")
    return RedirectResponse(url=_delivery_url(asset, None), status_code=307, headers={"Cache-Control": "no-store"})
