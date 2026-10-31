from ..config import get_settings
from .base import AvailabilityDTO, AvailabilityProvider, ProviderError, ProviderHTTP, ProviderNotConfigured, ProviderNotFound

_KIND = {"sub": "subscription", "free": "free", "rent": "rent", "buy": "buy", "tve": "subscription"}


class WatchmodeProvider(AvailabilityProvider):
    """Watchmode v1: country-specific streaming sources and their provider links.
    Each uncached lookup consumes API credits, hence the long TTLs (see TTL_AVAILABILITY)."""

    name = "watchmode"
    attribution = "Streaming availability data by Watchmode."

    def __init__(self, http: ProviderHTTP | None = None):
        s = get_settings()
        self._configured = bool(s.watchmode_api_key)
        self.http = http or ProviderHTTP("watchmode", "https://api.watchmode.com/v1", {},
                                         {"apiKey": s.watchmode_api_key})
        self.s = s

    def configured(self) -> bool:
        return self._configured

    def _find_id(self, ids: dict[str, str], type_: str) -> str | None:
        if "tmdb" in ids:
            field, value = ("tmdb_tv_id" if type_ == "series" else "tmdb_movie_id"), ids["tmdb"]
        elif "imdb" in ids:
            field, value = "imdb_id", ids["imdb"]
        else:
            return None  # never guess by name: a wrong match would show wrong links
        data = self.http.get("/search/", {"search_field": field, "search_value": value}, self.s.ttl_static)
        results = data.get("title_results") or []
        return str(results[0]["id"]) if results else None

    def availability(self, ids, type_, country) -> list[AvailabilityDTO]:
        if not self._configured:
            raise ProviderNotConfigured("Watchmode is not configured (set WATCHMODE_API_KEY)")
        try:
            wm_id = self._find_id(ids, type_)
            if not wm_id:
                return []
            rows = self.http.get(f"/title/{wm_id}/sources/", {"regions": country}, self.s.ttl_availability)
        except ProviderNotFound:
            return []
        if not isinstance(rows, list):
            raise ProviderError("watchmode: unexpected response")
        best: dict[tuple, AvailabilityDTO] = {}
        for r in rows:
            kind = _KIND.get(r.get("type"))
            if not kind or r.get("region") != country:
                continue
            k = (r.get("name"), kind)
            price = r.get("price")
            cur = best.get(k)
            if cur is None or (price is not None and (cur.price is None or price < cur.price)):
                best[k] = AvailabilityDTO(r.get("name", "Unknown"), kind, r.get("web_url"), price, r.get("format"),
                                          "watchmode")
        return list(best.values())
