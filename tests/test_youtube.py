import httpx
import pytest

from app.models import MediaAsset, TitleRight
from app.providers.base import ProviderHTTP
from app.providers.registry import get_registry
from app.providers.youtube import (
    YouTubeProvider, episode_length_fits, episode_title_matches, movie_length_fits, movie_title_matches, parse_duration,
)
from helpers import mk_episode, mk_title


# ---------------------------------------------------------------- pure matching rules
def test_parse_duration():
    assert parse_duration("PT1H52M3S") == 6723
    assert parse_duration("PT45M") == 2700
    assert parse_duration("P0D") is None and parse_duration(None) is None


@pytest.mark.parametrize("video, ok", [
    ("Avengers: Infinity War (2018) - Full Movie HD", True),
    ("AVENGERS INFINITY WAR | Full Movie [Hindi Dubbed]", True),
    ("Avengers: Infinity War Official Trailer", False),
    ("Avengers: Infinity War Review", False),
    ("Avengers: Infinity War - Ending Explained", False),
    ("Avengers: Endgame Full Movie", False),
    ("Avengers: Infinity War (1998) Full Movie", False),  # wrong year
])
def test_movie_title_rules(video, ok):
    assert movie_title_matches(video, "Avengers: Infinity War", 2018) is ok


def test_movie_title_with_the_word_movie_in_its_name():
    assert movie_title_matches("The Lego Movie (2014) Full Movie", "The Lego Movie", 2014)


def test_movie_length_rules():
    assert movie_length_fits(149 * 60, 149) and movie_length_fits(140 * 60, 149)
    assert not movie_length_fits(20 * 60, 149)       # a clip or recap
    assert not movie_length_fits(300 * 60, 149)      # a marathon or the wrong film
    assert movie_length_fits(95 * 60, None) and not movie_length_fits(30 * 60, None)


@pytest.mark.parametrize("video, ok", [
    ("Show Name S02E05 - The Bridge", True),
    ("Show Name Season 2 Episode 5", True),
    ("Show Name S02E06", False),                       # another episode
    ("Show Name Season 3 Episode 5", False),           # another season
    ("Show Name S02E05 Recap", False),
    ("Something Else S02E05", False),                  # another show
    ("Show Name - The Bridge", True),                  # no number, but the episode's own name
    ("Show Name - Pilot", False),
])
def test_episode_title_rules(video, ok):
    assert episode_title_matches(video, "Show Name", 2, 5, "The Bridge") is ok


def test_episode_length_rules():
    assert episode_length_fits(44 * 60, 45) and not episode_length_fits(3 * 60, 45)
    assert episode_length_fits(30 * 60, None) and not episode_length_fits(2 * 60, None)


# ---------------------------------------------------------------- the provider against a fake YouTube
def video(vid, title, dur="PT2H29M", embeddable=True, privacy="public", **extra):
    v = {"id": vid, "snippet": {"title": title, "channelTitle": "Studio"},
         "contentDetails": {"duration": dur, **extra},
         "status": {"embeddable": embeddable, "privacyStatus": privacy, "uploadStatus": "processed"}}
    return v


class FakeYouTube:
    def __init__(self, videos):
        self.videos = {v["id"]: v for v in videos}
        self.order = [v["id"] for v in videos]
        self.calls = []

    def __call__(self, request: httpx.Request):
        self.calls.append((request.url.path, dict(request.url.params)))
        p = dict(request.url.params)
        assert p.get("key") == "test-key"
        if request.url.path.endswith("/search"):
            assert p["videoType"] in ("movie", "episode") and p["videoEmbeddable"] == "true"
            return httpx.Response(200, json={"items": [{"id": {"videoId": i}} for i in self.order]})
        ids = p["id"].split(",")
        return httpx.Response(200, json={"items": [self.videos[i] for i in ids if i in self.videos]})


@pytest.fixture
def yt(monkeypatch):
    def make(videos):
        fake = FakeYouTube(videos)
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
        from app.config import get_settings
        get_settings.cache_clear()
        prov = YouTubeProvider(ProviderHTTP("youtube", "https://www.googleapis.com/youtube/v3", {}, {"key": "test-key"},
                                            transport=httpx.MockTransport(fake)))
        prov._key = "test-key"
        get_registry().youtube = prov
        return fake
    yield make
    from app.config import get_settings
    get_settings.cache_clear()


def test_picks_the_right_video_not_the_first_result(yt):
    yt([video("trailer1", "Dune Official Trailer", "PT3M"), video("wrongyr1", "Dune (1984) Full Movie", "PT2H17M"),
        video("blocked1", "Dune (2021) Full Movie", embeddable=False), video("good1234567", "Dune (2021) Full Movie", "PT2H35M")])
    m = get_registry().youtube.find_movie("Dune", 2021, 155)
    assert m and m.video_id == "good1234567" and m.embed_url == "https://www.youtube-nocookie.com/embed/good1234567"


def test_returns_none_instead_of_a_near_miss(yt):
    yt([video("a1", "Dune Official Trailer", "PT3M"), video("b1", "Dune Part Two Full Movie", "PT2H46M"),
        video("c1", "Dune (2021) Full Movie", "PT10M")])
    assert get_registry().youtube.find_movie("Dune", 2021, 155) is None


def test_private_or_unprocessed_videos_are_skipped(yt):
    yt([video("p1", "Dune (2021) Full Movie", "PT2H35M", privacy="unlisted")])
    assert get_registry().youtube.find_movie("Dune", 2021, 155) is None


# ---------------------------------------------------------------- Play end to end
def play(u, t, **kw):
    return u.post("/playback/sessions", json={"title_id": str(t.id), **kw})


def test_play_resolves_a_movie_once_and_reuses_it(make_user, db, yt):
    fake = yt([video("good1234567", "Open Film (2001) Full Movie", "PT1H40M")])
    t, u = mk_title(db, "Open Film"), make_user()
    t.runtime_minutes = 100
    db.commit()
    r = play(u, t)
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "embed" and r.json()["url"].endswith("/embed/good1234567")
    assert db.query(MediaAsset).filter_by(title_id=t.id).count() == 1
    right = db.query(TitleRight).filter_by(title_id=t.id).one()
    assert right.source == "youtube" and right.status == "verified" and "youtube.com/watch?v=good1234567" in right.evidence_url
    n = len(fake.calls)
    assert play(u, t).status_code == 201 and len(fake.calls) == n  # second Play does not search again


def test_play_with_no_match_is_refused_not_redirected_to_other_content(make_user, db, yt):
    yt([video("x1", "Some Other Film Full Movie", "PT1H40M")])
    t, u = mk_title(db, "Open Film"), make_user()
    r = play(u, t)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "no_rights"
    assert db.query(MediaAsset).count() == 0


def test_without_a_key_nothing_is_looked_up(make_user, db):
    t, u = mk_title(db, "Open Film"), make_user()
    assert get_registry().youtube is None or not get_registry().youtube.configured()
    assert play(u, t).status_code == 403
    assert db.query(MediaAsset).count() == 0


def test_series_play_starts_at_episode_one_and_each_episode_gets_its_own_video(make_user, db, yt):
    yt([video("ep1video0001", "Show S01E01 Full Episode", "PT44M"), video("ep2video0002", "Show S01E02 Full Episode", "PT44M")])
    t = mk_title(db, "Show", type_="series")
    e1, e2 = mk_episode(db, t, 1), mk_episode(db, t, 2)
    u = make_user()
    r = play(u, t).json()
    assert r["episode_id"] == str(e1.id) and r["url"].endswith("/embed/ep1video0001")
    u.delete(f"/playback/sessions/{r['session_id']}")  # a free plan has one screen
    r2 = play(u, t, episode_id=str(e2.id)).json()
    assert r2["url"].endswith("/embed/ep2video0002") and r2["previous_episode_id"] == str(e1.id)


def test_a_video_already_attached_to_another_title_is_blocked(make_user, db, yt):
    yt([video("same1234567", "Open Film (2001) Full Movie", "PT1H40M")])
    a, b, u = mk_title(db, "Open Film"), mk_title(db, "Open Film", year=2001), make_user()
    first = play(u, a)
    assert first.status_code == 201
    u.delete(f"/playback/sessions/{first.json()['session_id']}")
    r = play(u, b)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "source_conflict"
