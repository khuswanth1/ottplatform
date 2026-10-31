import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import audit, require_admin
from ..models import AuditLog, Episode, FeaturedTitle, MediaAsset, MediaJob, PlaybackReport, Season, Title, TitleMarker, TitleRight, User
from ..providers.base import NormalizedTitle, ProviderError
from ..providers.registry import get_registry
from ..schemas import (
    AdminTitleIn, AdminTitlePatch, AssetIn, AssetOut, AssetPatch, FeaturedIn, FeaturedOut, ImportIn, MarkerIn, MarkerOut, Msg, RightIn,
    RightOut, RightPatch,
    TitleCard, UserAdminPatch,
)
from ..services import catalog as svc
from ..services import transcode
from .playback import host_allowed, url_conflict

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _title(db: Session, tid: uuid.UUID) -> Title:
    t = db.get(Title, tid)
    if not t:
        raise HTTPException(404, "Title not found.")
    return t


# ------------------------------------------------------------------ titles
@router.get("/titles", response_model=dict)
def list_titles(q: str | None = None, status: str | None = None, page: int = Query(1, ge=1),
                db: Session = Depends(get_db)):
    stmt = select(Title)
    if q:
        stmt = stmt.where(Title.norm_name.like(f"%{svc.norm_name(q)}%"))
    if status:
        stmt = stmt.where(Title.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Title.updated_at.desc()).limit(30).offset((page - 1) * 30)).unique().all()
    return {"total": total, "page": page, "items": [
        {**svc.to_card(t, {}).model_dump(mode="json"), "status": t.status, "source": t.source} for t in rows]}


def _apply_title_fields(db: Session, t: Title, data: dict) -> None:
    genres = data.pop("genres", None)
    poster, backdrop = data.pop("poster_url", None), data.pop("backdrop_url", None)
    for k, v in data.items():
        setattr(t, k, v)
    if poster is not None:
        t.poster_path = poster
    if backdrop is not None:
        t.backdrop_path = backdrop
    if "name" in data:
        t.norm_name = svc.norm_name(t.name)
    if "release_date" in data:
        t.year = t.release_date.year if t.release_date else None
    if data.get("original_language"):
        svc.ensure_languages(db, {data["original_language"]})
    if genres is not None:
        g = svc.ensure_genres(db, set(genres))
        t.genres = [g[n] for n in genres if n in g]


@router.post("/titles", response_model=dict, status_code=201)
def create_title(body: AdminTitleIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    t = Title(type=body.type, name=body.name, norm_name=svc.norm_name(body.name), source="admin")
    _apply_title_fields(db, t, body.model_dump(exclude={"type"}))
    db.add(t)
    db.flush()
    audit(db, request, admin, "title.create", "title", t.id, {"name": t.name})
    db.commit()
    return {"id": str(t.id)}


@router.patch("/titles/{title_id}", response_model=TitleCard)
def update_title(title_id: uuid.UUID, body: AdminTitlePatch, request: Request, admin: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    t = _title(db, title_id)
    data = body.model_dump(exclude_unset=True)
    _apply_title_fields(db, t, dict(data))
    if set(data) - {"status"}:
        t.source = "admin"  # curated metadata is no longer overwritten by provider syncs
    audit(db, request, admin, "title.update", "title", t.id, {"fields": sorted(data)})
    db.commit()
    return svc.to_card(t, {})


@router.delete("/titles/{title_id}", response_model=Msg)
def archive_title(title_id: uuid.UUID, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    t = _title(db, title_id)
    t.status = "archived"
    audit(db, request, admin, "title.archive", "title", t.id)
    db.commit()
    return Msg(message="Title archived (hidden from the catalog; playback disabled).")


@router.post("/titles/import", response_model=dict, status_code=201)
def import_title(body: ImportIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Import a title by provider id. Archive imports arrive as a DRAFT with UNVERIFIED rights - nothing is playable."""
    reg = get_registry()
    try:
        if body.provider == "tmdb":
            prov = reg.primary_metadata
            if not prov:
                raise HTTPException(503, "TMDB is not configured.")
            nt = prov.details(body.type, body.external_id, "en-US")
            (t, _), = svc.upsert_titles(db, [nt])
            svc.apply_details(db, t, nt)
        else:
            arch = next((p for p in reg.free if p.name == "archive" and p.configured()), None)
            if not arch:
                raise HTTPException(503, "Internet Archive provider is disabled.")
            info = arch.files(body.external_id)
            nt = NormalizedTitle(provider="archive", external_id=body.external_id, type="movie",
                                 name=info["title"] or body.external_id, synopsis=info.get("description"),
                                 poster_path=f"https://archive.org/services/img/{body.external_id}")
            (t, _), = svc.upsert_titles(db, [nt])
            t.source, t.status = "admin", "draft"
            if not db.scalar(select(TitleRight.id).where(TitleRight.title_id == t.id)):
                db.add(TitleRight(
                    title_id=t.id, license_type=info.get("suggested_license_type") or "unknown", status="unverified",
                    territories=["*"], evidence_url=info.get("license_url") or info["details_url"], source="archive",
                    notes="Imported from Internet Archive. Uploads are user-submitted; verify the actual rights holder/license."))
    except ProviderError as e:
        raise HTTPException(502, f"Provider error: {e}")
    audit(db, request, admin, "title.import", "title", t.id, {"provider": body.provider, "external_id": body.external_id})
    db.commit()
    return {"id": str(t.id), "status": t.status}


@router.get("/archive/search")
def archive_search(q: str = Query(min_length=2, max_length=100), page: int = Query(1, ge=1), open_only: bool = True):
    arch = next((p for p in get_registry().free if p.name == "archive" and p.configured()), None)
    if not arch:
        raise HTTPException(503, "Internet Archive provider is disabled.")
    try:
        items = arch.search_candidates(q, page, open_only)
    except ProviderError as e:
        raise HTTPException(502, f"Provider error: {e}")
    return [{"identifier": i.external_id, "title": i.name, "year": i.release_date.year if i.release_date else None,
             "license_url": i.extra_ids.get("license_url") or None, "poster": i.poster_path,
             "note": "Candidate only - rights unverified."} for i in items]


@router.get("/archive/{identifier}/files")
def archive_files(identifier: str):
    arch = next((p for p in get_registry().free if p.name == "archive" and p.configured()), None)
    if not arch:
        raise HTTPException(503, "Internet Archive provider is disabled.")
    try:
        return arch.files(identifier)
    except (ProviderError, ValueError) as e:
        raise HTTPException(502, f"Provider error: {e}")


# ------------------------------------------------------------------ media assets
def _check_asset(db: Session, data: dict, kind: str | None, url: str | None, title_id=None, episode_id=None,
                 asset_id=None) -> None:
    if kind == "embed" and url and not host_allowed(url, get_settings().embed_allowed_hosts):
        raise HTTPException(422, "Embed host is not on the approved list (EMBED_ALLOWED_HOSTS).")
    if url and title_id and url_conflict(db, url, title_id, episode_id, exclude_id=asset_id):
        raise HTTPException(409, "This URL is already attached to a different title or episode. Each stream may belong to only one.")


@router.get("/media-assets", response_model=list[AssetOut])
def list_assets(title_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    stmt = select(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(200)
    if title_id:
        stmt = stmt.where(MediaAsset.title_id == title_id)
    return db.scalars(stmt).all()


@router.post("/media-assets", response_model=AssetOut, status_code=201)
def create_asset(body: AssetIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    t = _title(db, body.title_id)
    if body.episode_id:
        ep = db.get(Episode, body.episode_id)
        if not ep or ep.title_id != t.id:
            raise HTTPException(422, "Episode does not belong to this title.")
    elif t.type == "series":
        raise HTTPException(422, "Series assets must be attached to an episode.")
    _check_asset(db, {}, body.kind, body.url, t.id, body.episode_id)
    a = MediaAsset(**body.model_dump(exclude={"subtitles"}), subtitles=[s.model_dump() for s in body.subtitles],
                   created_by=admin.id)
    db.add(a)
    db.flush()
    audit(db, request, admin, "asset.create", "media_asset", a.id, {"title_id": str(t.id), "kind": a.kind})
    db.commit()
    return a


@router.patch("/media-assets/{asset_id}", response_model=AssetOut)
def update_asset(asset_id: uuid.UUID, body: AssetPatch, request: Request, admin: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    a = db.get(MediaAsset, asset_id)
    if not a:
        raise HTTPException(404, "Asset not found.")
    data = body.model_dump(exclude_unset=True)
    _check_asset(db, data, a.kind, data.get("url"), a.title_id, a.episode_id, a.id)
    if "subtitles" in data and data["subtitles"] is not None:
        data["subtitles"] = [s.model_dump() if hasattr(s, "model_dump") else s for s in body.subtitles]
    for k, v in data.items():
        setattr(a, k, v)
    audit(db, request, admin, "asset.update", "media_asset", a.id, {"fields": sorted(data)})
    db.commit()
    return a


@router.delete("/media-assets/{asset_id}", response_model=Msg)
def delete_asset(asset_id: uuid.UUID, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    a = db.get(MediaAsset, asset_id)
    if not a:
        raise HTTPException(404, "Asset not found.")
    audit(db, request, admin, "asset.delete", "media_asset", a.id)
    db.delete(a)
    db.commit()
    return Msg(message="Asset deleted.")


# ------------------------------------------------------------------ rights
@router.get("/title-rights", response_model=list[RightOut])
def list_rights(title_id: uuid.UUID | None = None, status: str | None = None, db: Session = Depends(get_db)):
    stmt = select(TitleRight).limit(200)
    if title_id:
        stmt = stmt.where(TitleRight.title_id == title_id)
    if status:
        stmt = stmt.where(TitleRight.status == status)
    return db.scalars(stmt).all()


@router.post("/title-rights", response_model=RightOut, status_code=201)
def create_right(body: RightIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    _title(db, body.title_id)
    if body.starts_at and body.expires_at and body.expires_at <= body.starts_at:
        raise HTTPException(422, "expires_at must be after starts_at.")
    r = TitleRight(**body.model_dump(), status="unverified", source="admin")  # always starts unverified
    db.add(r)
    db.flush()
    audit(db, request, admin, "right.create", "title_right", r.id, {"title_id": str(r.title_id)})
    db.commit()
    return r


@router.patch("/title-rights/{right_id}", response_model=RightOut)
def update_right(right_id: uuid.UUID, body: RightPatch, request: Request, admin: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    r = db.get(TitleRight, right_id)
    if not r:
        raise HTTPException(404, "Right not found.")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(r, k, v)
    if r.status == "verified" and set(data) & {"license_type", "evidence_url"}:
        r.status = "unverified"  # changing the legal basis requires fresh verification
    audit(db, request, admin, "right.update", "title_right", r.id, {"fields": sorted(data)})
    db.commit()
    return r


@router.post("/title-rights/{right_id}/verify", response_model=RightOut)
def verify_right(right_id: uuid.UUID, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(TitleRight, right_id)
    if not r:
        raise HTTPException(404, "Right not found.")
    if r.license_type == "unknown" or not r.evidence_url:
        raise HTTPException(422, "A concrete license_type and an evidence_url are required before verifying.")
    r.status, r.verified_by, r.verified_at = "verified", admin.id, datetime.now(timezone.utc)
    audit(db, request, admin, "right.verify", "title_right", r.id, {"license": r.license_type, "evidence": r.evidence_url})
    db.commit()
    return r


# ------------------------------------------------------------------ users / audit
@router.patch("/users/{user_id}", response_model=Msg)
def update_user(user_id: uuid.UUID, body: UserAdminPatch, request: Request, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found.")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(u, k, v)
    audit(db, request, admin, "user.update", "user", u.id, data)
    db.commit()
    return Msg(message="User updated.")


@router.get("/audit-logs")
def audit_logs(before_id: int | None = None, limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if before_id:
        stmt = stmt.where(AuditLog.id < before_id)
    return [{"id": a.id, "actor": str(a.actor_user_id) if a.actor_user_id else None, "action": a.action,
             "entity_type": a.entity_type, "entity_id": a.entity_id, "detail": a.detail,
             "created_at": a.created_at.isoformat()} for a in db.scalars(stmt)]


# ------------------------------------------------------------------ featured (home billboard)
@router.get("/featured", response_model=list[FeaturedOut])
def list_featured(db: Session = Depends(get_db)):
    rows = db.execute(select(FeaturedTitle, Title).join(Title, Title.id == FeaturedTitle.title_id)
                      .order_by(FeaturedTitle.country, FeaturedTitle.position)).all()
    return [FeaturedOut(id=f.id, country=f.country, position=f.position, starts_at=f.starts_at, ends_at=f.ends_at,
                        title=svc.to_card(t, {})) for f, t in rows]


@router.post("/featured", response_model=Msg, status_code=201)
def upsert_featured(body: FeaturedIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    t = _title(db, body.title_id)
    if t.status != "published":
        raise HTTPException(400, "Only published titles can be featured.")
    if body.starts_at and body.ends_at and body.ends_at <= body.starts_at:
        raise HTTPException(400, "ends_at must be after starts_at.")
    country = body.country.upper() if body.country != "*" else "*"
    row = db.scalar(select(FeaturedTitle).where(FeaturedTitle.title_id == t.id, FeaturedTitle.country == country))
    if not row:
        row = FeaturedTitle(title_id=t.id, country=country)
        db.add(row)
    row.position, row.starts_at, row.ends_at = body.position, body.starts_at, body.ends_at
    db.flush()
    audit(db, request, admin, "featured.set", "featured_title", row.id, {"title_id": str(t.id), "country": country})
    db.commit()
    return Msg(message="saved")


@router.delete("/featured/{featured_id}", response_model=Msg)
def delete_featured(featured_id: uuid.UUID, request: Request, admin: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    row = db.get(FeaturedTitle, featured_id)
    if not row:
        raise HTTPException(404, "Not found.")
    audit(db, request, admin, "featured.remove", "featured_title", row.id, {"title_id": str(row.title_id)})
    db.delete(row)
    db.commit()
    return Msg(message="removed")


# ------------------------------------------------------------------ skip markers
@router.get("/markers", response_model=list[MarkerOut])
def list_markers(title_id: uuid.UUID, db: Session = Depends(get_db)):
    return db.scalars(select(TitleMarker).where(TitleMarker.title_id == title_id).order_by(TitleMarker.episode_key, TitleMarker.start_s)).all()


@router.put("/markers", response_model=MarkerOut)
def set_marker(body: MarkerIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Create or replace the intro, recap or credits range of one film or episode."""
    t = _title(db, body.title_id)
    if body.end_s <= body.start_s:
        raise HTTPException(400, "The end must be after the start.")
    if t.type == "series":
        ep = db.get(Episode, body.episode_id) if body.episode_id else None
        if not ep or ep.title_id != t.id:
            raise HTTPException(400, "A series marker needs the episode it belongs to.")
    elif body.episode_id:
        raise HTTPException(400, "Movies have no episodes.")
    key = str(body.episode_id) if body.episode_id else "-"
    row = db.scalar(select(TitleMarker).where(TitleMarker.title_id == t.id, TitleMarker.episode_key == key, TitleMarker.kind == body.kind))
    if not row:
        row = TitleMarker(title_id=t.id, episode_id=body.episode_id, episode_key=key, kind=body.kind)
        db.add(row)
    row.start_s, row.end_s = body.start_s, body.end_s
    db.flush()
    audit(db, request, admin, "marker.set", "title_marker", row.id, {"title_id": str(t.id), "kind": body.kind})
    db.commit()
    return row


@router.delete("/markers/{marker_id}", response_model=Msg)
def delete_marker(marker_id: uuid.UUID, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(TitleMarker, marker_id)
    if not row:
        raise HTTPException(404, "Not found.")
    audit(db, request, admin, "marker.remove", "title_marker", row.id, {"title_id": str(row.title_id), "kind": row.kind})
    db.delete(row)
    db.commit()
    return Msg(message="removed")


# ------------------------------------------------------------------ playback problem reports
@router.get("/playback-reports", response_model=dict)
def list_playback_reports(status: str = Query("open", pattern="^(open|resolved|all)$"), page: int = Query(1, ge=1),
                          db: Session = Depends(get_db)):
    stmt = (select(PlaybackReport, Title.name, Season.number, Episode.number)
            .join(Title, Title.id == PlaybackReport.title_id)
            .outerjoin(Episode, Episode.id == PlaybackReport.episode_id)
            .outerjoin(Season, Season.id == Episode.season_id))
    if status != "all":
        stmt = stmt.where(PlaybackReport.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(PlaybackReport.created_at.desc()).limit(30).offset((page - 1) * 30)).all()
    return {"total": total, "page": page, "items": [{
        "id": str(r.id), "title_id": str(r.title_id), "title": name, "kind": r.kind, "note": r.note,
        "episode": f"S{sn}E{en}" if sn is not None and en is not None else None,
        "position_seconds": r.position_seconds, "user_agent": r.user_agent, "status": r.status,
        "created_at": r.created_at, "resolved_at": r.resolved_at,
    } for r, name, sn, en in rows]}


@router.post("/playback-reports/{report_id}/resolve", response_model=dict)
def resolve_playback_report(report_id: uuid.UUID, request: Request, admin: User = Depends(require_admin),
                            db: Session = Depends(get_db)):
    r = db.get(PlaybackReport, report_id)
    if not r:
        raise HTTPException(404, "Report not found.")
    if r.status != "resolved":
        r.status, r.resolved_at = "resolved", datetime.now(timezone.utc)
        audit(db, request, admin, "playback_report.resolve", "playback_report", r.id)
        db.commit()
    return {"id": str(r.id), "status": r.status}


# ------------------------------------------------------------------ video processing jobs
class MediaJobIn(BaseModel):
    title_id: uuid.UUID
    episode_id: uuid.UUID | None = None
    source: str = Field(min_length=1, max_length=300, description="file path inside <MEDIA_STORAGE_DIR>/incoming")


def _job_out(j: MediaJob) -> dict:
    return {"id": str(j.id), "title_id": str(j.title_id), "episode_id": str(j.episode_id) if j.episode_id else None,
            "source": j.source, "status": j.status, "attempts": j.attempts, "error": j.error,
            "asset_id": str(j.asset_id) if j.asset_id else None, "renditions": j.renditions, "duration_s": j.duration_s,
            "created_at": j.created_at, "finished_at": j.finished_at}


@router.post("/media-jobs", response_model=dict, status_code=202)
def create_media_job(body: MediaJobIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Queue a source file for processing into adaptive HLS. Returns at once; a worker does the transcoding."""
    t = _title(db, body.title_id)
    if body.episode_id:
        ep = db.get(Episode, body.episode_id)
        if not ep or ep.title_id != t.id:
            raise HTTPException(422, "Episode does not belong to this title.")
    elif t.type == "series":
        raise HTTPException(422, "Series sources must be attached to an episode.")
    try:
        job = transcode.enqueue(db, t.id, body.episode_id, body.source, admin.id)
    except transcode.TranscodeError as e:
        raise HTTPException(409 if "already has a job" in str(e) else 422, str(e))
    audit(db, request, admin, "media_job.create", "media_job", job.id, {"title_id": str(t.id), "source": body.source})
    db.commit()
    return _job_out(job)


@router.get("/media-jobs", response_model=dict)
def list_media_jobs(status: str | None = Query(None, pattern="^(queued|processing|ready|failed)$"),
                    title_id: uuid.UUID | None = None, page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    stmt = select(MediaJob)
    if status:
        stmt = stmt.where(MediaJob.status == status)
    if title_id:
        stmt = stmt.where(MediaJob.title_id == title_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(MediaJob.created_at.desc()).limit(30).offset((page - 1) * 30)).all()
    return {"total": total, "page": page, "items": [_job_out(j) for j in rows]}


@router.post("/media-jobs/{job_id}/retry", response_model=dict)
def retry_media_job(job_id: uuid.UUID, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    j = db.get(MediaJob, job_id)
    if not j:
        raise HTTPException(404, "Job not found.")
    try:
        transcode.requeue(db, j)
    except transcode.TranscodeError as e:
        raise HTTPException(409, str(e))
    audit(db, request, admin, "media_job.retry", "media_job", j.id)
    db.commit()
    return _job_out(j)
