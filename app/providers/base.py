"""Provider adapter contracts. A new licensed provider = one class implementing any of these capabilities,
registered through EXTRA_PROVIDERS="package.module:ClassName" - no change to the core application."""
import time
from dataclasses import dataclass, field
from datetime import date

import httpx

from .. import metrics
from ..cache import Loaded, cache
from ..config import get_settings


class ProviderError(Exception):
    """Provider unavailable / failed (after retries). Callers degrade gracefully."""


class ProviderNotConfigured(ProviderError):
    pass


class ProviderNotFound(ProviderError):
    pass


@dataclass
class CastDTO:
    name: str
    character: str | None = None
    person_id: str | None = None
    profile_path: str | None = None


@dataclass
class CrewDTO:
    name: str
    job: str | None = None
    department: str | None = None
    person_id: str | None = None
    profile_path: str | None = None



@dataclass
class SeasonDTO:
    number: int
    name: str | None = None
    overview: str | None = None
    air_date: date | None = None
    poster_path: str | None = None
    episode_count: int = 0


@dataclass
class EpisodeDTO:
    number: int
    name: str | None = None
    overview: str | None = None
    air_date: date | None = None
    runtime: int | None = None
    still_path: str | None = None


@dataclass
class NormalizedTitle:
    provider: str
    external_id: str
    type: str  # movie | series
    name: str
    original_name: str | None = None
    synopsis: str | None = None
    release_date: date | None = None
    runtime: int | None = None
    original_language: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    vote_average: float | None = None
    popularity: float | None = None
    genres: list[str] = field(default_factory=list)
    extra_ids: dict[str, str] = field(default_factory=dict)
    cast: list[CastDTO] = field(default_factory=list)
    crew: list[CrewDTO] = field(default_factory=list)
    seasons: list[SeasonDTO] = field(default_factory=list)
    audio_languages: list[str] = field(default_factory=list)
    age_rating: str | None = None
    adult: bool = False
    detailed: bool = False


@dataclass
class Page:
    items: list[NormalizedTitle]
    page: int = 1
    total_pages: int = 1
    stale: bool = False


@dataclass
class AvailabilityDTO:
    provider_name: str
    kind: str  # free | subscription | rent | buy
    web_url: str | None = None
    price: float | None = None
    format: str | None = None
    source: str = ""


class MetadataProvider:
    name = ""
    attribution = ""

    def configured(self) -> bool:
        return True

    def section(self, section: str, type_: str, page: int, language: str, original_language: str | None,
                genre_names: list[str], year: int | None, origin_country: str | None = None,
                watch_region: str | None = None, monetization: str | None = None) -> Page: ...

    def trailer(self, type_: str, external_id: str, language: str, season_number: int | None = None) -> dict | None: ...

    def season_videos(self, external_id: str, season_number: int, language: str = "en-US") -> list[dict]:
        return []

    def search(self, q: str, type_: str | None, page: int, language: str, year: int | None) -> Page: ...

    def discover_by_person(self, person_name: str, type_: str, page: int, language: str) -> Page: ...

    def details(self, type_: str, external_id: str, language: str) -> NormalizedTitle: ...

    def season(self, external_id: str, number: int, language: str) -> list[EpisodeDTO]: ...

    def genres(self, language: str) -> dict[str, str]: ...  # name -> id as strings

    def languages(self) -> list[dict]: ...

    def keyword_movies(self, keyword_id: str | int, page: int = 1, language: str = "en-US") -> Page:
        return Page([], page, 1)

    def person_credits(self, person_id: str | int, type_: str = "movie", language: str = "en-US") -> dict:
        return {}

    def person_translations(self, person_id: str | int) -> list[dict]:
        return []

    def collection_translations(self, collection_id: str | int) -> list[dict]:
        return []

    def watch_providers_list(self, type_: str = "movie", language: str = "en-US", watch_region: str | None = None) -> list[dict]:
        return []

    def season_watch_providers(self, series_id: str | int, season_number: int, language: str = "en-US") -> dict:
        return {}

    def guest_session_rated(self, guest_session_id: str, kind: str = "movies", page: int = 1,
                            sort_by: str = "created_at.asc", language: str = "en-US") -> dict:
        return {}


class AvailabilityProvider:
    name = ""
    attribution = ""

    def configured(self) -> bool:
        return True

    def availability(self, ids: dict[str, str], type_: str, country: str) -> list[AvailabilityDTO]: ...


class FreeContentProvider:
    """Finds *candidates* only. Nothing becomes playable until an admin verifies rights and approves an asset."""
    name = ""

    def configured(self) -> bool:
        return True

    def search_candidates(self, q: str, page: int) -> list[NormalizedTitle]: ...

    def files(self, identifier: str) -> dict: ...


_breaker: dict[str, tuple[int, float]] = {}  # provider -> (consecutive failures, open_until)


class ProviderHTTP:
    """GET-JSON client: timeouts, bounded retries with backoff, ETag revalidation, circuit breaker,
    shared (single-flight) caching and stale-if-error. API keys are passed separately and never cached/logged."""

    def __init__(self, name: str, base_url: str, headers: dict | None = None, secret_params: dict | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.secret_params = secret_params or {}
        self._client = httpx.Client(
            timeout=httpx.Timeout(get_settings().provider_timeout_s, connect=3.0),
            headers={"User-Agent": "ott-platform/1.0", "Accept": "application/json", **self.headers},
            transport=transport,
            follow_redirects=False,
        )

    def get(self, path: str, params: dict | None = None, ttl: int = 3600) -> dict | list:
        params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        key = f"{self.name}:{path}:" + "&".join(f"{k}={params[k]}" for k in sorted(params))

        def load():
            stale = cache.get_entry(key)
            hdrs = {"If-None-Match": stale.etag} if stale and stale.etag else {}
            resp = self._request(path, {**params, **self.secret_params}, hdrs)
            if resp.status_code == 304 and stale:
                return Loaded(stale.value, stale.etag)
            return Loaded(resp.json(), resp.headers.get("etag"))

        value, state = cache.get_or_load(key, ttl, load)
        metrics.inc("provider_cache_total", provider=self.name, state=state)
        return value

    def _request(self, path: str, params: dict, headers: dict) -> httpx.Response:
        s = get_settings()
        fails, open_until = _breaker.get(self.name, (0, 0.0))
        if open_until > time.time():
            raise ProviderError(f"{self.name} temporarily unavailable (circuit open)")
        last: Exception | None = None
        for attempt in range(s.provider_retries + 1):
            try:
                resp = self._client.get(self.base_url + path, params=params, headers=headers)
                if resp.status_code in (429, 500, 502, 503, 504):
                    last = ProviderError(f"{self.name} returned {resp.status_code}")
                    delay = min(float(resp.headers.get("retry-after", 0) or 0), 2.0) or 0.3 * 2**attempt
                    metrics.inc("provider_retry_total", provider=self.name)
                    time.sleep(delay)
                    continue
                if resp.status_code == 404:
                    raise ProviderNotFound(f"{self.name}: not found")
                if resp.status_code in (401, 403):
                    raise ProviderError(f"{self.name}: credentials rejected ({resp.status_code})")
                if resp.status_code == 304:
                    _breaker[self.name] = (0, 0.0)
                    return resp
                resp.raise_for_status()
                _breaker[self.name] = (0, 0.0)
                return resp
            except ProviderNotFound:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = ProviderError(f"{self.name} network error: {type(e).__name__}")
                metrics.inc("provider_retry_total", provider=self.name)
                time.sleep(0.3 * 2**attempt)
            except httpx.HTTPStatusError as e:
                last = ProviderError(f"{self.name} returned {e.response.status_code}")
                break
        fails += 1
        _breaker[self.name] = (fails, time.time() + 30 if fails >= 5 else 0.0)
        metrics.inc("provider_failure_total", provider=self.name)
        raise last or ProviderError(f"{self.name} failed")


def reset_breakers() -> None:
    _breaker.clear()
