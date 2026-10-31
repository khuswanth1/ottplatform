import re
from datetime import date

from ..config import get_settings
from .base import FreeContentProvider, NormalizedTitle, ProviderHTTP

_TAGS = re.compile(r"<[^>]+>")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def classify_license(url: str | None) -> str | None:
    """Suggestion only. An admin must still verify the actual rights before anything is playable."""
    if not url:
        return None
    u = url.lower()
    if "publicdomain" in u:
        return "public_domain"
    if "creativecommons.org" in u:
        return "creative_commons"
    return None


def _first(v):
    return v[0] if isinstance(v, list) and v else v


class ArchiveProvider(FreeContentProvider):
    """Internet Archive advanced-search + metadata APIs. Results are *candidates*: Archive uploads are
    user-submitted and frequently NOT public domain, so playback requires explicit admin rights verification."""

    name = "archive"

    def __init__(self, http: ProviderHTTP | None = None):
        s = get_settings()
        self._enabled = s.archive_enabled
        self.http = http or ProviderHTTP("archive", "https://archive.org", {}, {})
        self.s = s

    def configured(self) -> bool:
        return self._enabled

    def search_candidates(self, q: str, page: int = 1, open_only: bool = False) -> list[NormalizedTitle]:
        phrase = q.replace('"', " ").strip()
        query = f'title:("{phrase}") AND mediatype:(movies)'
        if open_only:  # only items that declare a public-domain / Creative Commons license URL
            query += " AND licenseurl:(*publicdomain* OR *creativecommons*)"
        data = self.http.get("/advancedsearch.php", {
            "q": query, "fl[]": ["identifier", "title", "description", "year", "licenseurl", "language", "downloads"],
            "rows": 20, "page": page, "output": "json", "sort[]": "downloads desc",
        }, self.s.ttl_search)
        out = []
        for d in (data.get("response") or {}).get("docs", []):
            ident = d.get("identifier")
            if not ident or not _SAFE_ID.match(ident):
                continue
            year = _first(d.get("year"))
            desc = _first(d.get("description")) or ""
            t = NormalizedTitle(
                provider="archive", external_id=ident, type="movie", name=str(_first(d.get("title")) or ident),
                synopsis=_TAGS.sub("", desc)[:2000] or None,
                release_date=date(int(year), 1, 1) if str(year).isdigit() else None,
                poster_path=f"https://archive.org/services/img/{ident}",
            )
            t.extra_ids["license_url"] = _first(d.get("licenseurl")) or ""
            out.append(t)
        return out

    def files(self, identifier: str) -> dict:
        if not _SAFE_ID.match(identifier):
            raise ValueError("invalid identifier")
        data = self.http.get(f"/metadata/{identifier}", {}, self.s.ttl_details)
        meta = data.get("metadata") or {}
        lic = _first(meta.get("licenseurl"))
        playable = []
        for f in data.get("files", []):
            fmt, name = f.get("format", ""), f.get("name", "")
            if name.lower().endswith((".mp4", ".m4v", ".webm", ".ogv")) and "thumb" not in fmt.lower():
                playable.append({"name": name, "format": fmt, "size": f.get("size"),
                                 "url": f"https://archive.org/download/{identifier}/{name}"})
        return {
            "identifier": identifier, "title": _first(meta.get("title")), "license_url": lic,
            "description": _TAGS.sub("", str(_first(meta.get("description")) or ""))[:2000] or None,
            "year": _first(meta.get("year")),
            "suggested_license_type": classify_license(lic), "files": playable[:50],
            "embed_url": f"https://archive.org/embed/{identifier}", "details_url": f"https://archive.org/details/{identifier}",
        }
