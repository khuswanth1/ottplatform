"""Video processing: admin queues a source file, a worker turns it into an adaptive HLS ladder.

Flow: POST /admin/media-jobs (row, status=queued) -> worker `claim_next` -> ffprobe -> one ffmpeg run producing every
rendition + master playlist into a temp dir -> poster frame -> atomic rename to hls/<job id>/ -> MediaAsset(kind=hls) ->
status=ready. Only then can the title play, and only once an admin has also verified the title's rights (nothing here
creates or verifies a right). Nothing in this module runs inside a request handler.

Failures are recorded on the row (tail of ffmpeg's stderr), retried up to `transcode_max_attempts`, and can be re-queued
by an admin. A job whose worker died is reclaimed after `transcode_lease_s`."""
import json
import logging
import os
import shutil
import socket
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import metrics
from ..config import get_settings
from ..models import MediaAsset, MediaJob

log = logging.getLogger("ott.transcode")

SOURCE_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi", ".ts"}
# (height, video kbit/s, audio kbit/s). Only rungs not taller than the source are produced (never upscale).
LADDER = [(1080, 5000, 192), (720, 2800, 128), (480, 1400, 128), (360, 800, 96)]
SEGMENT_S = 6


class TranscodeError(Exception):
    pass


def storage_root() -> Path:
    return Path(get_settings().media_storage_dir).resolve()


def resolve_source(rel: str) -> Path:
    """The file an admin named, which must exist inside <storage>/incoming (no traversal, no symlink escape)."""
    base = (storage_root() / "incoming").resolve()
    p = (base / rel).resolve()
    if base not in p.parents or not p.is_file() or p.suffix.lower() not in SOURCE_EXTS:
        raise TranscodeError("Source must be an existing video file inside the incoming folder.")
    return p


# ------------------------------------------------------------------ pure ffmpeg planning
def pick_renditions(source_height: int) -> list[tuple[int, int, int]]:
    rungs = [r for r in LADDER if r[0] <= source_height]
    return rungs or [LADDER[-1]]  # tiny source: one rung, ffmpeg scales to the smallest (even-sized) output


def build_hls_command(src: Path, out: Path, renditions: list[tuple[int, int, int]], has_audio: bool, *,
                      ffmpeg: str = "ffmpeg", preset: str = "veryfast") -> list[str]:
    """One ffmpeg process, N renditions, keyframes aligned across them so the player can switch at any segment."""
    n = len(renditions)
    split = "".join(f"[v{i}]" for i in range(n))
    chains = [f"[0:v]split={n}{split}"] + [
        f"[v{i}]scale=-2:{h}:flags=bicubic[v{i}out]" for i, (h, _, _) in enumerate(renditions)]
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(src), "-filter_complex", ";".join(chains)]
    for i, (_, vk, ak) in enumerate(renditions):
        cmd += ["-map", f"[v{i}out]", f"-c:v:{i}", "libx264", f"-preset", preset, f"-b:v:{i}", f"{vk}k",
                f"-maxrate:v:{i}", f"{int(vk * 1.07)}k", f"-bufsize:v:{i}", f"{vk * 2}k", "-profile:v", "main", "-pix_fmt", "yuv420p"]
        if has_audio:
            cmd += ["-map", "a:0", f"-c:a:{i}", "aac", f"-b:a:{i}", f"{ak}k", "-ac", "2"]
    cmd += ["-force_key_frames", f"expr:gte(t,n_forced*{SEGMENT_S})", "-sc_threshold", "0"]
    stream_map = " ".join((f"v:{i},a:{i}" if has_audio else f"v:{i}") + f",name:{renditions[i][0]}p" for i in range(n))
    cmd += ["-f", "hls", "-hls_time", str(SEGMENT_S), "-hls_playlist_type", "vod", "-hls_flags", "independent_segments",
            "-hls_segment_filename", str(out / "%v_%05d.ts"), "-master_pl_name", "master.m3u8",
            "-var_stream_map", stream_map, str(out / "%v.m3u8")]
    return cmd


def build_poster_command(src: Path, out: Path, at_s: int, *, ffmpeg: str = "ffmpeg") -> list[str]:
    return [ffmpeg, "-hide_banner", "-nostdin", "-y", "-ss", str(at_s), "-i", str(src), "-frames:v", "1",
            "-vf", "scale=-2:720", "-q:v", "3", str(out / "poster.jpg")]


def parse_probe(raw: str) -> dict:
    """ffprobe -show_streams -show_format JSON -> {height, duration_s, has_audio}. Rejects files with no video."""
    try:
        data = json.loads(raw)
    except ValueError:
        raise TranscodeError("ffprobe returned unreadable output.")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video" and s.get("height")), None)
    if not video:
        raise TranscodeError("The file has no video stream.")
    try:
        dur = float((data.get("format") or {}).get("duration") or video.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    if dur <= 0:
        raise TranscodeError("Could not read the video's duration.")
    return {"height": int(video["height"]), "duration_s": int(dur), "has_audio": any(s.get("codec_type") == "audio" for s in streams)}


def media_url(job_id: uuid.UUID) -> str:
    return f"{get_settings().media_public_base.rstrip('/')}/{job_id}/master.m3u8"


# ------------------------------------------------------------------ process execution (injectable for tests)
def run_command(cmd: list[str], timeout: int) -> str:
    """Runs without a shell. Returns stdout; raises TranscodeError with the tail of stderr on failure or timeout."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        raise TranscodeError(f"{cmd[0]} is not installed on this worker.")
    except subprocess.TimeoutExpired:
        raise TranscodeError(f"{Path(cmd[0]).name} timed out after {timeout}s.")
    if r.returncode != 0:
        raise TranscodeError(f"{Path(cmd[0]).name} exited {r.returncode}: {(r.stderr or '')[-1500:]}")
    return r.stdout


# ------------------------------------------------------------------ queue
def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def enqueue(db: Session, title_id: uuid.UUID, episode_id: uuid.UUID | None, source: str, by: uuid.UUID | None) -> MediaJob:
    resolve_source(source)  # fail now, not on the worker
    job = MediaJob(title_id=title_id, episode_id=episode_id, episode_key=str(episode_id) if episode_id else "-",
                   source=source, created_by=by)
    db.add(job)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise TranscodeError("This title or episode already has a job waiting or running.")
    return job


def claim_next(db: Session, worker_id: str, now: datetime | None = None) -> MediaJob | None:
    """Takes one runnable job: queued, or processing past its lease (worker died). SKIP LOCKED on PostgreSQL lets several
    workers poll at once without blocking or double-claiming."""
    s, now = get_settings(), now or datetime.now(timezone.utc)
    stmt = (select(MediaJob).where(or_(MediaJob.status == "queued",
                                       (MediaJob.status == "processing")
                                       & (MediaJob.locked_at < now - timedelta(seconds=s.transcode_lease_s))))
            .order_by(MediaJob.created_at).limit(1))
    if db.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    job = db.scalar(stmt)
    if not job:
        return None
    if job.attempts >= s.transcode_max_attempts:  # an orphaned job that has already used its tries
        job.status, job.error, job.finished_at = "failed", job.error or "Worker stopped repeatedly.", now
        db.commit()
        return claim_next(db, worker_id, now)
    job.status, job.locked_by, job.locked_at, job.attempts = "processing", worker_id, now, job.attempts + 1
    db.commit()
    return job


def process(db: Session, job: MediaJob, run=run_command) -> None:
    """Runs one claimed job to ready/queued(retry)/failed. Never raises for a bad file; always leaves the row consistent."""
    s = get_settings()
    final = storage_root() / "hls" / str(job.id)
    tmp = storage_root() / "hls" / f".tmp-{job.id}"
    try:
        src = resolve_source(job.source)
        info = parse_probe(run([s.ffprobe_bin, "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                                str(src)], 120))
        rungs = pick_renditions(info["height"])
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        run(build_hls_command(src, tmp, rungs, info["has_audio"], ffmpeg=s.ffmpeg_bin, preset=s.transcode_preset),
            s.transcode_timeout_s)
        try:  # the poster is a nicety: a failure here must not fail the video
            run(build_poster_command(src, tmp, min(10, info["duration_s"] // 2), ffmpeg=s.ffmpeg_bin), 120)
        except TranscodeError as e:
            log.warning("poster failed job=%s: %s", job.id, e)
        if not (tmp / "master.m3u8").is_file() or not any(tmp.glob("*.ts")):
            raise TranscodeError("ffmpeg finished but produced no playlist or segments.")
        shutil.rmtree(final, ignore_errors=True)
        os.replace(tmp, final)  # outputs appear all at once or not at all
        asset = MediaAsset(title_id=job.title_id, episode_id=job.episode_id, kind="hls", url=media_url(job.id),
                           requires_signing=False,  # same-origin /vod is gated by the viewer's session (authorize-vod)
                           created_by=job.created_by)
        db.add(asset)
        db.flush()
        job.asset_id, job.status, job.error = asset.id, "ready", None
        job.renditions = [{"height": h, "video_kbps": v} for h, v, _ in rungs]
        job.duration_s, job.finished_at = info["duration_s"], datetime.now(timezone.utc)
        db.commit()
        metrics.inc("transcode_jobs_total", result="ready")
        log.info("transcode ready job=%s rungs=%s", job.id, [r[0] for r in rungs])
    except Exception as e:  # TranscodeError, OSError, DB errors: record, never crash the worker loop
        db.rollback()
        shutil.rmtree(tmp, ignore_errors=True)
        job = db.get(MediaJob, job.id)
        msg = str(e) if isinstance(e, TranscodeError) else f"{type(e).__name__}: {e}"
        job.error = msg[-1800:]
        retry = job.attempts < s.transcode_max_attempts and not _permanent(e)
        job.status = "queued" if retry else "failed"
        job.locked_by = job.locked_at = None
        job.finished_at = None if retry else datetime.now(timezone.utc)
        db.commit()
        metrics.inc("transcode_jobs_total", result="retry" if retry else "failed")
        log.error("transcode %s job=%s attempt=%s: %s", "will retry" if retry else "FAILED", job.id, job.attempts, msg[:300])


def _permanent(e: Exception) -> bool:
    """Bad input will not get better by retrying; infrastructure hiccups might."""
    return isinstance(e, TranscodeError) and any(k in str(e) for k in ("no video stream", "duration", "inside the incoming"))


def requeue(db: Session, job: MediaJob) -> None:
    if job.status != "failed":
        raise TranscodeError("Only failed jobs can be retried.")
    job.status, job.attempts, job.error, job.finished_at = "queued", 0, None, None
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise TranscodeError("This title or episode already has a job waiting or running.")


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"
