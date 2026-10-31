import re
from datetime import date, timedelta

from ..config import get_settings
from .base import (
    AvailabilityDTO, AvailabilityProvider, CastDTO, CrewDTO, EpisodeDTO, MetadataProvider, NormalizedTitle, Page,
    ProviderHTTP, ProviderNotConfigured, SeasonDTO,
)

DOC_GENRE = "99"
# our availability filter -> TMDB monetization types (TMDB joins alternatives with '|')
MONETIZATION = {"subscription": "flatrate", "free": "free|ads", "rent": "rent", "buy": "buy"}


def _d(v: str | None) -> date | None:
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


class TMDBProvider(MetadataProvider, AvailabilityProvider):
    """TMDB v3. Attribution required by TMDB terms: "This product uses the TMDB API but is not endorsed or
    certified by TMDB." Availability fallback data is supplied by JustWatch (attribution required)."""

    name = "tmdb"
    attribution = "This product uses the TMDB API but is not endorsed or certified by TMDB."

    def __init__(self, http: ProviderHTTP | None = None):
        s = get_settings()
        self._configured = bool(s.tmdb_read_token or s.tmdb_api_key)
        headers = {"Authorization": f"Bearer {s.tmdb_read_token}"} if s.tmdb_read_token else {}
        secret = {} if s.tmdb_read_token or not s.tmdb_api_key else {"api_key": s.tmdb_api_key}
        self.http = http or ProviderHTTP("tmdb", "https://api.themoviedb.org/3", headers, secret)
        self.ttl = s

    def configured(self) -> bool:
        return self._configured

    def _get(self, path: str, params: dict | None = None, ttl: int | None = None):
        if not self._configured:
            raise ProviderNotConfigured("TMDB is not configured (set TMDB_READ_TOKEN)")
        return self.http.get(path, params, ttl or self.ttl.ttl_lists)

    # ---- genres / languages ----
    def genres(self, language: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for kind in ("movie", "tv"):
            data = self._get(f"/genre/{kind}/list", {"language": language}, self.ttl.ttl_static)
            for g in data.get("genres", []):
                out.setdefault(g["name"], str(g["id"]))
        return out

    def _genre_names(self, ids: list[int], language: str) -> list[str]:
        by_id = {v: k for k, v in self.genres(language).items()}
        return [by_id[str(i)] for i in ids if str(i) in by_id]

    def languages(self) -> list[dict]:
        data = self._get("/configuration/languages", {}, self.ttl.ttl_static)
        return [{"code": x["iso_639_1"], "name": x.get("name") or x["english_name"], "english_name": x["english_name"]}
                for x in data]

    # ---- mapping ----
    def _list_item(self, r: dict, forced_type: str | None, language: str) -> NormalizedTitle | None:
        mt = r.get("media_type") or forced_type
        if mt not in ("movie", "tv"):
            return None
        is_tv = mt == "tv"
        name = r.get("name") if is_tv else r.get("title")
        if not name:
            return None
        return NormalizedTitle(
            provider="tmdb", external_id=str(r["id"]), type="series" if is_tv else "movie", name=name,
            original_name=r.get("original_name") if is_tv else r.get("original_title"),
            synopsis=r.get("overview") or None,
            release_date=_d(r.get("first_air_date") if is_tv else r.get("release_date")),
            original_language=r.get("original_language"), poster_path=r.get("poster_path"),
            backdrop_path=r.get("backdrop_path"), vote_average=r.get("vote_average"), popularity=r.get("popularity"),
            genres=self._genre_names(r.get("genre_ids", []), language), adult=bool(r.get("adult")),
        )

    def _page(self, data: dict, forced_type: str | None, language: str) -> Page:
        items = [t for r in data.get("results", []) if (t := self._list_item(r, forced_type, language))]
        return Page(items, data.get("page", 1), min(data.get("total_pages", 1), 500))

    # ---- listings ----
    def section(self, section, type_, page, language, original_language, genre_names, year,
                origin_country=None, watch_region=None, monetization=None) -> Page:
        kind = "tv" if type_ == "series" else "movie"
        gmap = self.genres(language)
        gids = [gmap[g] for g in genre_names if g in gmap]
        mono = MONETIZATION.get(monetization or "")
        filtered = bool(original_language or gids or year or origin_country or (mono and watch_region))
        today = date.today().isoformat()
        base = {"language": language, "page": page, "include_adult": "false"}
        if section == "upcoming" or filtered:
            p = {**base, "sort_by": "popularity.desc"}
            if original_language:
                p["with_original_language"] = original_language
            if gids:
                p["with_genres"] = ",".join(gids)
            if origin_country:
                p["with_origin_country"] = origin_country.upper()
            if mono and watch_region:  # TMDB requires watch_region alongside monetization filters
                p["watch_region"] = watch_region.upper()
                p["with_watch_monetization_types"] = mono
            if section == "top_rated":
                p.update(sort_by="vote_average.desc", **{"vote_count.gte": 200})
            if section == "upcoming":
                key = "first_air_date" if kind == "tv" else "primary_release_date"
                p[f"{key}.gte"] = (date.today() + timedelta(days=1)).isoformat()
                p[f"{key}.lte"] = (date.today() + timedelta(days=270)).isoformat()
            if year:
                p["first_air_date_year" if kind == "tv" else "primary_release_year"] = year
            data = self._get(f"/discover/{kind}", p)
            return self._page(data, kind, language)
        path = {
            "trending": f"/trending/{kind}/week",
            "trending_today": f"/trending/{kind}/day",
            "popular": f"/{kind}/popular",
            "top_rated": f"/{kind}/top_rated",
        }.get(section)
        if not path:
            raise ValueError(f"unknown section {section}")
        return self._page(self._get(path, base), kind, language)

    def search(self, q, type_, page, language, year) -> Page:
        p = {"query": q, "language": language, "page": page, "include_adult": "false"}
        if type_ in ("movie", "series"):
            kind = "tv" if type_ == "series" else "movie"
            if year:
                p["first_air_date_year" if kind == "tv" else "year"] = year
            return self._page(self._get(f"/search/{kind}", p, self.ttl.ttl_search), kind, language)
        data = self._get("/search/multi", p, self.ttl.ttl_search)
        data["results"] = [r for r in data.get("results", []) if r.get("media_type") in ("movie", "tv")]
        return self._page(data, None, language)

    def discover_by_person(self, person_name, type_, page, language) -> Page:
        people = self._get("/search/person", {"query": person_name, "include_adult": "false"},
                           self.ttl.ttl_search).get("results", [])
        if not people:
            return Page([], page, 1)
        kind = "tv" if type_ == "series" else "movie"
        data = self._get(f"/discover/{kind}", {"with_cast": people[0]["id"], "language": language, "page": page,
                                              "sort_by": "popularity.desc", "include_adult": "false"})
        return self._page(data, kind, language)

    # ---- trailer & season videos ----
    def trailer(self, type_, external_id, language, season_number: int | None = None) -> dict | None:
        """Best official YouTube trailer, else a teaser. Returns {site, key, name} or None."""
        kind = "tv" if type_ == "series" else "movie"
        if kind == "tv" and season_number is not None:
            path = f"/tv/{external_id}/season/{season_number}/videos"
        else:
            path = f"/{kind}/{external_id}/videos"
        data = self._get(path,
                         {"language": language, "include_video_language": f"{language},en,null"}, self.ttl.ttl_details)
        vids = [v for v in data.get("results", [])
                if v.get("site") == "YouTube" and v.get("key") and v.get("type") in ("Trailer", "Teaser")]
        if not vids and kind == "tv" and season_number is None:
            data = self._get(f"/tv/{external_id}/season/1/videos",
                             {"language": language, "include_video_language": f"{language},en,null"}, self.ttl.ttl_details)
            vids = [v for v in data.get("results", [])
                    if v.get("site") == "YouTube" and v.get("key") and v.get("type") in ("Trailer", "Teaser")]
        if not vids:
            return None
        # real trailer > teaser, official > fan, requested language first, then avoid regional/variant cuts,
        # then the earliest published (usually the main theatrical trailer)
        variant = re.compile(r"b&w|black|australian|\buk\b|dubbed|subtitled|international|imax|clip|featurette|re-?release", re.I)
        vids.sort(key=lambda v: (v["type"] != "Trailer", not v.get("official"), v.get("iso_639_1") != language,
                                 bool(variant.search(v.get("name") or "")), v.get("published_at") or "9999"))
        v = vids[0]
        return {"site": "YouTube", "key": v["key"], "name": v.get("name") or "Trailer"}

    def season_videos(self, external_id: str, season_number: int, language: str = "en-US") -> list[dict]:
        """Fetch all videos for a TV season from TMDB:
        https://api.themoviedb.org/3/tv/{series_id}/season/{season_number}/videos?language=en-US"""
        data = self._get(
            f"/tv/{external_id}/season/{season_number}/videos",
            {"language": language, "include_video_language": f"{language},en,null"},
            self.ttl.ttl_details,
        )
        results = []
        for v in data.get("results", []):
            if v.get("site") == "YouTube" and v.get("key"):
                results.append({
                    "id": v.get("id"),
                    "name": v.get("name"),
                    "key": v.get("key"),
                    "site": v.get("site"),
                    "type": v.get("type"),
                    "official": v.get("official", False),
                    "published_at": v.get("published_at"),
                    "embed_url": f"https://www.youtube-nocookie.com/embed/{v['key']}",
                })
        return results

    # ---- details ----
    def details(self, type_, external_id, language) -> NormalizedTitle:
        kind = "tv" if type_ == "series" else "movie"
        extra = "credits,external_ids," + ("content_ratings" if kind == "tv" else "release_dates")
        d = self._get(f"/{kind}/{external_id}", {"language": language, "append_to_response": extra},
                      self.ttl.ttl_details)
        t = self._list_item({**d, "media_type": kind, "genre_ids": []}, kind, language)
        if t is None:
            raise ValueError("unmappable TMDB response")
        t.genres = [g["name"] for g in d.get("genres", [])]
        t.runtime = (d.get("episode_run_time") or [None])[0] if kind == "tv" else d.get("runtime")
        t.synopsis = d.get("overview") or None
        t.audio_languages = [x["iso_639_1"] for x in d.get("spoken_languages", []) if x.get("iso_639_1")]
        imdb = (d.get("external_ids") or {}).get("imdb_id") or d.get("imdb_id")
        if imdb:
            t.extra_ids["imdb"] = imdb
        t.cast = [CastDTO(c["name"], c.get("character"), str(c["id"]), c.get("profile_path"))
                  for c in (d.get("credits") or {}).get("cast", [])[:20]]
        crew_raw = (d.get("credits") or {}).get("crew", [])
        creators = [
            CrewDTO(name=c["name"], job="Creator", department="Writing", person_id=str(c.get("id")), profile_path=c.get("profile_path"))
            for c in d.get("created_by", []) if c.get("name")
        ]
        key_priority = {
            "Director": 1, "Creator": 1, "Writer": 2, "Screenplay": 2, "Story": 2,
            "Producer": 3, "Executive Producer": 4, "Original Music Composer": 5,
            "Director of Photography": 6, "Editor": 7, "Production Design": 8
        }
        seen_crew = set()
        parsed_crew: list[CrewDTO] = []
        for c in creators:
            key = (c.name, c.job)
            if key not in seen_crew:
                seen_crew.add(key)
                parsed_crew.append(c)

        for c in crew_raw:
            job = c.get("job") or ""
            name = c.get("name") or ""
            if not name:
                continue
            key = (name, job)
            if key in seen_crew:
                continue
            seen_crew.add(key)
            parsed_crew.append(CrewDTO(
                name=name,
                job=job or None,
                department=c.get("department") or None,
                person_id=str(c.get("id")),
                profile_path=c.get("profile_path"),
            ))

        parsed_crew.sort(key=lambda x: key_priority.get(x.job, 99))
        t.crew = parsed_crew[:24]
        t.age_rating = self._us_rating(d, kind)
        if kind == "tv":
            t.seasons = [SeasonDTO(s["season_number"], s.get("name"), s.get("overview") or None, _d(s.get("air_date")),
                                   s.get("poster_path"), s.get("episode_count", 0))
                         for s in d.get("seasons", []) if s.get("season_number", 0) > 0]
        t.detailed = True
        return t

    @staticmethod
    def _us_rating(d: dict, kind: str) -> str | None:
        if kind == "tv":
            for r in (d.get("content_ratings") or {}).get("results", []):
                if r.get("iso_3166_1") == "US" and r.get("rating"):
                    return r["rating"]
            return None
        for r in (d.get("release_dates") or {}).get("results", []):
            if r.get("iso_3166_1") == "US":
                for rd in r.get("release_dates", []):
                    if rd.get("certification"):
                        return rd["certification"]
        return None

    def season(self, external_id, number, language) -> list[EpisodeDTO]:
        d = self._get(f"/tv/{external_id}/season/{number}", {"language": language}, self.ttl.ttl_details)
        return [EpisodeDTO(e["episode_number"], e.get("name"), e.get("overview") or None, _d(e.get("air_date")),
                           e.get("runtime"), e.get("still_path")) for e in d.get("episodes", [])]

    # ---- availability fallback (JustWatch data via TMDB; landing-page links, not deep links) ----
    def availability(self, ids, type_, country) -> list[AvailabilityDTO]:
        tid = ids.get("tmdb")
        if not tid:
            return []
        kind = "tv" if type_ == "series" else "movie"
        data = self._get(f"/{kind}/{tid}/watch/providers", {}, self.ttl.ttl_availability)
        c = (data.get("results") or {}).get(country)
        if not c:
            return []
        out = []
        for key, kind_label in (("flatrate", "subscription"), ("free", "free"), ("ads", "free"),
                                ("rent", "rent"), ("buy", "buy")):
            for p in c.get(key, []):
                out.append(AvailabilityDTO(p["provider_name"], kind_label, c.get("link"), None, None, "tmdb"))
        return out

    def keyword_movies(self, keyword_id: str | int, page: int = 1, language: str = "en-US") -> Page:
        p = {"language": language, "page": page, "include_adult": "false"}
        data = self._get(f"/keyword/{keyword_id}/movies", p, self.ttl.ttl_search)
        return self._page(data, "movie", language)

    def person_credits(self, person_id: str | int, type_: str = "movie", language: str = "en-US") -> dict:
        kind = "tv" if type_ == "series" else "movie"
        return self._get(f"/person/{person_id}/{kind}_credits", {"language": language}, self.ttl.ttl_details)

    def person_translations(self, person_id: str | int) -> list[dict]:
        data = self._get(f"/person/{person_id}/translations", {}, self.ttl.ttl_details)
        return data.get("translations", [])

    def collection_translations(self, collection_id: str | int) -> list[dict]:
        data = self._get(f"/collection/{collection_id}/translations", {}, self.ttl.ttl_details)
        return data.get("translations", [])

    def watch_providers_list(self, type_: str = "movie", language: str = "en-US", watch_region: str | None = None) -> list[dict]:
        kind = "tv" if type_ == "series" else "movie"
        p = {"language": language}
        if watch_region:
            p["watch_region"] = watch_region.upper()
        data = self._get(f"/watch/providers/{kind}", p, self.ttl.ttl_availability)
        return data.get("results", [])

    def season_watch_providers(self, series_id: str | int, season_number: int, language: str = "en-US") -> dict:
        data = self._get(f"/tv/{series_id}/season/{season_number}/watch/providers", {"language": language}, self.ttl.ttl_availability)
        return data.get("results", {})

    def guest_session_rated(self, guest_session_id: str, kind: str = "movies", page: int = 1,
                            sort_by: str = "created_at.asc", language: str = "en-US") -> dict:
        p = {"language": language, "page": page, "sort_by": sort_by}
        return self._get(f"/guest_session/{guest_session_id}/rated/{kind}", p, self.ttl.ttl_search)

