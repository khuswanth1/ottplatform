"""YouTube Data API v3 resolver: finds the one YouTube video that IS a given movie or episode, for playback through
YouTube's own embedded player (IFrame). Nothing is downloaded, proxied or scraped.

Authorised sources only: searches are restricted to YouTube's own `videoType=movie` (YouTube Movies) and
`videoType=episode` (YouTube Shows) catalogues, and only videos the owner allows to be embedded are accepted
(`videoEmbeddable`, `status.embeddable`). A loose "full movie" text search is never used, because that is how
re-uploads of other people's films turn up.

A match is accepted only when the video title names the same work and the length fits, so Play never lands on a
trailer, a review or a different film. When nothing passes, the caller gets None and shows "not playable here".

Quota: search.list costs 100 units and videos.list 1, against a default 10,000 a day, so about 100 searches a day.
Responses are cached for a day (negative answers too) and a result is stored as a media asset after the first Play."""
import re
import unicodedata
from dataclasses import dataclass

from ..config import get_settings
from .base import ProviderError, ProviderHTTP, ProviderNotConfigured

EMBED_BASE = "https://www.youtube-nocookie.com/embed/"
WATCH_BASE = "https://www.youtube.com/watch?v="

# words that mark a video as something other than the work itself
_NOT_THE_WORK = re.compile(
    r"\b(trailer|teaser|promo|clip|clips|scene|scenes|review|reaction|reacts?|explained|explanation|recap|breakdown|"
    r"behind the scenes|making of|bloopers?|interview|featurette|soundtrack|song|songs|jukebox|ost|shorts?|"
    r"audio|podcast|analysis|ending|theory|top \d+|compilation|fan ?made|parody|spoof)\b", re.I)
# harmless decoration around a title
_DECORATION = re.compile(
    r"\b(full|movie|film|episode|hd|4k|uhd|free|official|with ads|english|hindi|tamil|telugu|dubbed|subtitles?|subbed|"
    r"watch|now|new|latest|streaming)\b", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[\(\[][^)\]]*[\)\]]", " ", s)  # (2018), [HD]
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def parse_duration(iso: str | None) -> int | None:
    """ISO 8601 'PT1H52M3S' -> seconds."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return (d * 86400 + h * 3600 + mi * 60 + s) or None


@dataclass
class YouTubeMatch:
    video_id: str
    title: str
    channel: str
    duration_s: int
    allowed_regions: list[str] | None  # None = no allow-list (worldwide unless blocked)
    blocked_regions: list[str]

    @property
    def embed_url(self) -> str:
        return EMBED_BASE + self.video_id

    @property
    def watch_url(self) -> str:
        return WATCH_BASE + self.video_id


def _stripped_title(video_title: str) -> str:
    return norm(_DECORATION.sub(" ", video_title))


def movie_title_matches(video_title: str, name: str, year: int | None) -> bool:
    if _NOT_THE_WORK.search(video_title):
        return False
    want = norm(name)
    if not want or _stripped_title(video_title) != norm(_DECORATION.sub(" ", name)):
        return False
    years = {int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", video_title)}
    wanted_year_in_name = {int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", name)}
    years -= wanted_year_in_name
    return not (year and years and not any(abs(y - year) <= 1 for y in years))


def movie_length_fits(duration_s: int, runtime_min: int | None) -> bool:
    if runtime_min:
        return 0.80 * runtime_min * 60 <= duration_s <= 1.30 * runtime_min * 60
    return duration_s >= 60 * 60  # no runtime known: a feature is at least an hour


def episode_title_matches(video_title: str, series: str, season: int, number: int, ep_name: str | None) -> bool:
    if _NOT_THE_WORK.search(video_title):
        return False
    t = norm(video_title)
    if norm(series) not in t:
        return False
    tag = re.search(rf"\bs0?{season}\s?e0?{number}\b", t) or re.search(
        rf"\bseason {season} episode {number}\b|\bs{season} ep {number}\b|\bseason {season} ep {number}\b", t)
    if tag:
        return True
    # a different explicit episode number means a different episode
    other = re.search(r"\bs0?(\d+)\s?e0?(\d+)\b|\bseason (\d+) episode (\d+)\b|\bepisode (\d+)\b", t)
    if other:
        g = other.groups()
        if g[0] is not None:
            return (int(g[0]), int(g[1])) == (season, number)
        if g[2] is not None:
            return (int(g[2]), int(g[3])) == (season, number)
        return season == 1 and int(g[4]) == number
    return bool(ep_name) and len(norm(ep_name)) >= 4 and norm(ep_name) in t


def episode_length_fits(duration_s: int, runtime_min: int | None) -> bool:
    if runtime_min:
        return 0.60 * runtime_min * 60 <= duration_s <= 1.60 * runtime_min * 60
    return 10 * 60 <= duration_s <= 3 * 3600


class YouTubeProvider:
    name = "youtube"

    def __init__(self, http: ProviderHTTP | None = None):
        s = get_settings()
        self._key = s.youtube_api_key
        self.http = http or ProviderHTTP("youtube", "https://www.googleapis.com/youtube/v3", {}, {"key": self._key})
        self._ttl = s.youtube_cache_s

    def configured(self) -> bool:
        return bool(self._key) and not self._key.startswith("GOCSPX-")

    # ---- API calls ----
    def _search(self, q: str, video_type: str, region: str | None) -> list[str]:
        if not self.configured():
            raise ProviderNotConfigured("YouTube is not configured (set YOUTUBE_API_KEY)")
        data = self.http.get("/search", {
            "part": "snippet", "type": "video", "videoType": video_type, "videoEmbeddable": "true",
            "videoSyndicated": "true", "safeSearch": "none", "maxResults": 8, "q": q,
            "regionCode": region.upper() if region and len(region) == 2 else None,
        }, self._ttl)
        return [i["id"]["videoId"] for i in data.get("items", []) if i.get("id", {}).get("videoId")]

    def _details(self, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        data = self.http.get("/videos", {"part": "snippet,contentDetails,status", "id": ",".join(ids)}, self._ttl)
        by_id = {v["id"]: v for v in data.get("items", [])}
        return [by_id[i] for i in ids if i in by_id]  # keep YouTube's relevance order

    @staticmethod
    def _usable(v: dict) -> bool:
        st = v.get("status", {})
        return bool(st.get("embeddable")) and st.get("privacyStatus") == "public" and st.get("uploadStatus") == "processed"

    @staticmethod
    def _to_match(v: dict, duration_s: int) -> YouTubeMatch:
        rr = (v.get("contentDetails") or {}).get("regionRestriction") or {}
        return YouTubeMatch(v["id"], v["snippet"]["title"], v["snippet"].get("channelTitle", ""), duration_s,
                            rr.get("allowed"), rr.get("blocked") or [])

    # ---- public ----
    def find_movie(self, name: str, year: int | None, runtime_min: int | None, region: str | None = None) -> YouTubeMatch | None:
        q = f"{name} {year}" if year else name
        for v in self._details(self._search(q, "movie", region)):
            d = parse_duration((v.get("contentDetails") or {}).get("duration"))
            if (d and self._usable(v) and movie_title_matches(v["snippet"]["title"], name, year)
                    and movie_length_fits(d, runtime_min)):
                return self._to_match(v, d)
        return None

    def find_episode(self, series: str, season: int, number: int, ep_name: str | None, runtime_min: int | None,
                     region: str | None = None) -> YouTubeMatch | None:
        q = f"{series} season {season} episode {number}"
        for v in self._details(self._search(q, "episode", region)):
            d = parse_duration((v.get("contentDetails") or {}).get("duration"))
            if (d and self._usable(v) and episode_title_matches(v["snippet"]["title"], series, season, number, ep_name)
                    and episode_length_fits(d, runtime_min)):
                return self._to_match(v, d)
        return None


__all__ = ["YouTubeProvider", "YouTubeMatch", "ProviderError"]
