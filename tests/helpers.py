from datetime import datetime, timedelta, timezone

from app.models import Episode, MediaAsset, Season, Title, TitleRight
from app.services.catalog import norm_name


def mk_title(db, name="Open Film", type_="movie", kids=False, status="published", year=2001):
    t = Title(type=type_, name=name, norm_name=norm_name(name), status=status, is_kids_safe=kids, year=year, source="admin")
    db.add(t)
    db.commit()
    return t


def mk_episode(db, title, number=1, season_no=1):
    s = db.query(Season).filter_by(title_id=title.id, number=season_no).first()
    if not s:
        s = Season(title_id=title.id, number=season_no)
        db.add(s)
        db.flush()
    e = Episode(season_id=s.id, title_id=title.id, number=number, name=f"Ep {number}")
    db.add(e)
    db.commit()
    return e


def mk_asset(db, title, kind="hls", url="https://cdn.example.com/a/index.m3u8", episode=None, **kw):
    a = MediaAsset(title_id=title.id, episode_id=episode.id if episode else None, kind=kind, url=url, **kw)
    db.add(a)
    db.commit()
    return a


def mk_right(db, title, status="verified", territories=("*",), entitlement="registered", starts=None, expires=None,
             license_type="public_domain"):
    r = TitleRight(title_id=title.id, license_type=license_type, status=status, territories=list(territories),
                   entitlement=entitlement, starts_at=starts, expires_at=expires, evidence_url="https://proof.example/1")
    db.add(r)
    db.commit()
    return r


def days(n):
    return datetime.now(timezone.utc) + timedelta(days=n)
