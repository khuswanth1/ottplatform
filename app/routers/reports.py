from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_profile, require_verified
from ..maturity import blocked
from ..models import Episode, PlaybackReport, Profile, Title, User
from ..ratelimit import rate_limit
from ..schemas import PlaybackReportIn

router = APIRouter(prefix="/playback/reports", tags=["playback"])


@router.post("", status_code=201, dependencies=[Depends(rate_limit("playback_report", 10, 3600))])
def report_problem(body: PlaybackReportIn, request: Request, user: User = Depends(require_verified),
                   profile: Profile = Depends(get_profile), db: Session = Depends(get_db)):
    t = db.get(Title, body.title_id)
    if not t or t.status != "published" or blocked(profile, t):
        raise HTTPException(404, "Title not found.")
    if body.episode_id:
        ep = db.get(Episode, body.episode_id)
        if not ep or ep.title_id != t.id:
            raise HTTPException(400, "That episode does not belong to this title.")
    note = (body.note or "").strip() or None
    # the same person reporting the same problem again updates the open report instead of piling up
    r = db.scalar(select(PlaybackReport).where(
        PlaybackReport.user_id == user.id, PlaybackReport.title_id == t.id,
        PlaybackReport.episode_id == body.episode_id, PlaybackReport.kind == body.kind,
        PlaybackReport.status == "open"))
    if r:
        r.note, r.position_seconds = note or r.note, body.position_seconds
    else:
        r = PlaybackReport(user_id=user.id, title_id=t.id, episode_id=body.episode_id, kind=body.kind, note=note,
                           position_seconds=body.position_seconds,
                           user_agent=(request.headers.get("user-agent") or "")[:200] or None)
        db.add(r)
    db.commit()
    return {"id": str(r.id), "status": r.status}
