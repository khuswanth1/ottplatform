import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import transcode_worker
from app.config import get_settings
from app.models import MediaAsset
from app.services import transcode as tc
from helpers import mk_right, mk_title

PROBE = {"streams": [{"codec_type": "video", "height": 1080}, {"codec_type": "audio"}], "format": {"duration": "120.5"}}


@pytest.fixture
def media(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "media_storage_dir", str(tmp_path))
    (tmp_path / "incoming").mkdir()
    (tmp_path / "incoming" / "film.mp4").write_bytes(b"x")
    return tmp_path


class FakeFfmpeg:
    """Stands in for ffprobe/ffmpeg: answers probes and writes the files a real run would."""

    def __init__(self, probe=PROBE, fail_times=0, poster_fails=False, empty=False):
        self.probe, self.fail_times, self.poster_fails, self.empty = probe, fail_times, poster_fails, empty
        self.calls = []

    def __call__(self, cmd, timeout):
        self.calls.append(cmd)
        if Path(cmd[0]).name == "ffprobe":
            return json.dumps(self.probe)
        if "poster.jpg" in cmd[-1]:
            if self.poster_fails:
                raise tc.TranscodeError("poster boom")
            Path(cmd[-1]).write_bytes(b"jpg")
            return ""
        if self.fail_times > 0:
            self.fail_times -= 1
            raise tc.TranscodeError("ffmpeg exited 1: Conversion failed!")
        if not self.empty:
            out = Path(cmd[-1]).parent
            (out / "master.m3u8").write_text("#EXTM3U")
            (out / "1080p_00000.ts").write_bytes(b"ts")
        return ""


def queue(db, title=None, source="film.mp4"):
    t = title or mk_title(db)
    job = tc.enqueue(db, t.id, None, source, None)
    db.commit()
    return t, job


# ---------------------------------------------------------------- pure planning
@pytest.mark.parametrize("h,expected", [(2160, [1080, 720, 480, 360]), (720, [720, 480, 360]), (500, [480, 360]),
                                        (240, [360])])
def test_ladder_never_upscales(h, expected):
    assert [r[0] for r in tc.pick_renditions(h)] == expected


def test_hls_command_has_aligned_keyframes_all_renditions_and_no_shell():
    rungs = tc.pick_renditions(1080)
    cmd = tc.build_hls_command(Path("/in/f.mp4"), Path("/out"), rungs, True)
    assert isinstance(cmd, list) and "-force_key_frames" in cmd and "-master_pl_name" in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert fc.startswith("[0:v]split=4") and fc.count("scale=-2:") == 4
    assert cmd[cmd.index("-var_stream_map") + 1] == "v:0,a:0,name:1080p v:1,a:1,name:720p v:2,a:2,name:480p v:3,a:3,name:360p"
    silent = tc.build_hls_command(Path("/in/f.mp4"), Path("/out"), rungs[:1], False)
    assert "a:0" not in " ".join(silent) and silent[silent.index("-var_stream_map") + 1] == "v:0,name:1080p"


def test_probe_parsing_rejects_bad_files():
    assert tc.parse_probe(json.dumps(PROBE)) == {"height": 1080, "duration_s": 120, "has_audio": True}
    for bad in ("not json", json.dumps({"streams": [{"codec_type": "audio"}], "format": {"duration": "5"}}),
                json.dumps({"streams": [{"codec_type": "video", "height": 10}], "format": {}})):
        with pytest.raises(tc.TranscodeError):
            tc.parse_probe(bad)


@pytest.mark.parametrize("src", ["../secret.mp4", "/etc/passwd", "missing.mp4", "notes.txt", ""])
def test_source_must_be_a_real_video_inside_incoming(media, src):
    (media / "secret.mp4").write_bytes(b"x")
    (media / "incoming" / "notes.txt").write_text("x")
    with pytest.raises(tc.TranscodeError):
        tc.resolve_source(src)


# ---------------------------------------------------------------- processing
def test_job_becomes_an_hls_asset(media, db):
    t, job = queue(db)
    claimed = tc.claim_next(db, "w1")
    assert claimed.id == job.id and claimed.status == "processing" and claimed.attempts == 1
    tc.process(db, claimed, FakeFfmpeg())
    db.refresh(job)
    assert job.status == "ready" and job.error is None and job.duration_s == 120
    assert [r["height"] for r in job.renditions] == [1080, 720, 480, 360]
    asset = db.get(MediaAsset, job.asset_id)
    assert (asset.kind, asset.title_id, asset.url) == ("hls", t.id, f"/vod/{job.id}/master.m3u8")
    out = media / "hls" / str(job.id)
    assert (out / "master.m3u8").is_file() and (out / "poster.jpg").is_file()
    assert not list((media / "hls").glob(".tmp-*"))


def test_poster_failure_does_not_fail_the_video(media, db):
    _, job = queue(db)
    tc.process(db, tc.claim_next(db, "w"), FakeFfmpeg(poster_fails=True))
    db.refresh(job)
    assert job.status == "ready"


def test_transient_failure_is_retried_then_succeeds(media, db):
    _, job = queue(db)
    ff = FakeFfmpeg(fail_times=1)
    tc.process(db, tc.claim_next(db, "w"), ff)
    db.refresh(job)
    assert job.status == "queued" and "Conversion failed" in job.error and job.locked_by is None
    assert not list((media / "hls").glob(".tmp-*"))
    tc.process(db, tc.claim_next(db, "w"), ff)
    db.refresh(job)
    assert job.status == "ready" and job.attempts == 2 and job.error is None


def test_job_fails_for_good_after_max_attempts_and_can_be_requeued(media, db):
    _, job = queue(db)
    ff = FakeFfmpeg(fail_times=99)
    for _ in range(get_settings().transcode_max_attempts):
        tc.process(db, tc.claim_next(db, "w"), ff)
    db.refresh(job)
    assert job.status == "failed" and job.finished_at and db.query(MediaAsset).count() == 0
    assert tc.claim_next(db, "w") is None
    tc.requeue(db, job)
    db.commit()
    assert job.status == "queued" and job.attempts == 0


def test_bad_input_fails_immediately_without_retries(media, db):
    _, job = queue(db)
    tc.process(db, tc.claim_next(db, "w"), FakeFfmpeg(probe={"streams": [], "format": {}}))
    db.refresh(job)
    assert job.status == "failed" and "no video stream" in job.error and job.attempts == 1


def test_ffmpeg_producing_nothing_is_not_a_ready_asset(media, db):
    _, job = queue(db)
    tc.process(db, tc.claim_next(db, "w"), FakeFfmpeg(empty=True))
    db.refresh(job)
    assert job.status == "queued" and "no playlist" in job.error and db.query(MediaAsset).count() == 0


def test_missing_ffmpeg_binary_is_reported_clearly(media, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "ffprobe_bin", "definitely-not-installed-ffprobe")
    _, job = queue(db)
    tc.process(db, tc.claim_next(db, "w"))  # real runner: the binary does not exist
    db.refresh(job)
    assert "not installed" in job.error


# ---------------------------------------------------------------- queue behaviour
def test_orphaned_job_is_reclaimed_only_after_its_lease(media, db):
    _, job = queue(db)
    tc.claim_next(db, "dead-worker")
    assert tc.claim_next(db, "w2") is None
    later = datetime.now(timezone.utc) + timedelta(seconds=get_settings().transcode_lease_s + 5)
    again = tc.claim_next(db, "w2", now=later)
    assert again.id == job.id and again.locked_by == "w2" and again.attempts == 2


def test_one_unfinished_job_per_title(media, db):
    t, _ = queue(db)
    with pytest.raises(tc.TranscodeError, match="already has a job"):
        tc.enqueue(db, t.id, None, "film.mp4", None)


def test_worker_loop_step(media, db):
    _, job = queue(db)
    assert transcode_worker.run_once("w", FakeFfmpeg()) is True
    assert transcode_worker.run_once("w", FakeFfmpeg()) is False
    db.refresh(job)
    assert job.status == "ready"


# ---------------------------------------------------------------- admin API
def test_admin_api_queues_lists_and_retries(make_admin, make_user, media, db):
    t = mk_title(db)
    a = make_admin()
    r = a.post("/admin/media-jobs", json={"title_id": str(t.id), "source": "film.mp4"})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert a.post("/admin/media-jobs", json={"title_id": str(t.id), "source": "film.mp4"}).status_code == 409
    assert a.post("/admin/media-jobs", json={"title_id": str(t.id), "source": "../x.mp4"}).status_code in (409, 422)
    assert a.get("/admin/media-jobs", params={"status": "queued"}).json()["total"] == 1
    assert a.post(f"/admin/media-jobs/{r.json()['id']}/retry").status_code == 409  # only failed jobs
    plain = make_user("plain@example.com")
    assert plain.post("/admin/media-jobs", json={"title_id": str(t.id), "source": "film.mp4"}).status_code == 403
    s = mk_title(db, "Show", type_="series")
    assert a.post("/admin/media-jobs", json={"title_id": str(s.id), "source": "film.mp4"}).status_code == 422


def test_api_request_never_runs_ffmpeg(make_admin, media, db, monkeypatch):
    monkeypatch.setattr(tc, "run_command", lambda *a, **k: pytest.fail("transcoding ran inside a request"))
    t = mk_title(db)
    assert make_admin().post("/admin/media-jobs", json={"title_id": str(t.id), "source": "film.mp4"}).status_code == 202


# ---------------------------------------------------------------- delivery authorization
def _ready_title(db):
    t, job = queue(db)
    tc.process(db, tc.claim_next(db, "w"), FakeFfmpeg())
    db.refresh(job)
    mk_right(db, t)
    return t, job


def _authz(user, job_id, name="720p_00003.ts"):
    return user.c.get("/api/v1/playback/authorize-vod", headers={"X-Original-URI": f"/vod/{job_id}/{name}"})


def test_segments_are_served_only_during_the_viewers_own_playback_session(make_user, media, db):
    t, job = _ready_title(db)
    viewer, other = make_user(), make_user("other@example.com")
    play = viewer.post("/playback/sessions", json={"title_id": str(t.id)})
    assert play.status_code == 201 and play.json()["url"] == f"/vod/{job.id}/master.m3u8"
    assert _authz(viewer, job.id).status_code == 204
    assert _authz(viewer, job.id, "master.m3u8").status_code == 204
    assert _authz(other, job.id).status_code == 403  # signed in, but no session of their own
    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app).get("/api/v1/playback/authorize-vod", headers={"X-Original-URI": f"/vod/{job.id}/a.ts"})
    assert anon.status_code == 403
    assert _authz(viewer, job.id, "../../etc/passwd").status_code == 403
    assert _authz(viewer, "not-a-uuid").status_code == 403
    viewer.delete(f"/playback/sessions/{play.json()['session_id']}")
    assert _authz(viewer, job.id).status_code == 403  # stopped: segments stop too


def test_unverified_rights_block_processed_video_too(make_user, media, db):
    t, _ = queue(db)
    tc.process(db, tc.claim_next(db, "w"), FakeFfmpeg())
    r = make_user().post("/playback/sessions", json={"title_id": str(t.id)})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "no_rights"  # processing never grants rights
