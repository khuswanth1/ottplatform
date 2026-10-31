"""Per-profile maturity levels.

kids  -> the existing family-safe flag (Title.is_kids_safe)
7+    -> ratings up to age 8 (G, PG, TV-Y, TV-Y7, TV-G) plus anything already family-safe
13+   -> ratings up to age 14 (adds TV-PG, PG-13, TV-14)
all   -> no limit

Unrated or unknown ratings are only shown at "all" (or when the title is flagged family-safe): when we cannot tell,
the restricted profile does not see it. Ratings come from US certifications, so this is a content filter, not a
parental-control product (see README, known limitations)."""
from __future__ import annotations

LEVELS = ("kids", "7+", "13+", "all")
_CAP = {"7+": 8, "13+": 14}
_AGE = {
    "G": 0, "TV-Y": 0, "TV-G": 0, "TV-Y7": 7, "TV-Y7-FV": 7, "PG": 8, "TV-PG": 10,
    "PG-13": 13, "TV-14": 14, "R": 17, "NC-17": 18, "TV-MA": 18,
}


def rating_age(rating: str | None) -> int | None:
    return _AGE.get(rating.strip().upper()) if rating else None


def title_allowed(title, level: str | None) -> bool:
    """title needs .is_kids_safe and .age_rating"""
    if not level or level == "all":
        return True
    if title.is_kids_safe:
        return True
    if level == "kids":
        return False
    age = rating_age(title.age_rating)
    return age is not None and age <= _CAP[level]


def profile_level(profile) -> str:
    return (getattr(profile, "maturity_level", None) or "all") if profile else "all"


def blocked(profile, title) -> bool:
    return bool(profile) and not title_allowed(title, profile_level(profile))
