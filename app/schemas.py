import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator

from .config import get_settings


class Msg(BaseModel):
    message: str


# ---------- auth ----------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class EmailIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=10, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    role: str
    plan: str
    email_verified: bool


# ---------- profiles ----------
AVATAR_PATTERN = r"^avatar-([1-9]|1[0-9]|2[0-4])$"  # avatar-1 to avatar-24; the app draws twelve, the rest are room to grow


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    avatar: str = Field(default="avatar-1", pattern=AVATAR_PATTERN)
    language: str = Field(default="en", pattern=r"^[a-z]{2,3}$")
    is_kids: bool = False  # legacy; maturity_level wins when both are sent
    maturity_level: Literal["kids", "7+", "13+", "all"] | None = None


class ProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    avatar: str | None = Field(default=None, pattern=AVATAR_PATTERN)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")
    is_kids: bool | None = None
    maturity_level: Literal["kids", "7+", "13+", "all"] | None = None


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    avatar: str
    language: str
    is_kids: bool
    maturity_level: str = "all"
    has_pin: bool = False


class PinSet(BaseModel):
    pin: str | None = Field(default=None, pattern=r"^[0-9]{4}$")  # null clears the PIN
    password: str = Field(min_length=1, max_length=256)


class PinUnlock(BaseModel):
    pin: str = Field(pattern=r"^[0-9]{4}$")


# ---------- catalog ----------
class DirectAccess(BaseModel):
    entitlement: Literal["registered", "premium"]
    label: str


class TitleCard(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    year: int | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    vote_average: float | None = None
    original_language: str | None = None
    genres: list[str] = []
    age_rating: str | None = None
    is_kids_safe: bool = False
    runtime_minutes: int | None = None
    release_date: date | None = None
    direct: DirectAccess | None = None  # set only when authorized playback exists on this platform


class CastOut(BaseModel):
    name: str
    character: str | None = None
    profile_url: str | None = None


class CrewOut(BaseModel):
    name: str
    job: str | None = None
    department: str | None = None
    profile_url: str | None = None


class SeasonOut(BaseModel):
    id: uuid.UUID
    number: int
    name: str | None = None
    episode_count: int = 0
    air_date: date | None = None


class TitleDetail(TitleCard):
    synopsis: str | None = None
    release_date: date | None = None
    runtime_minutes: int | None = None
    cast: list[CastOut] = []
    crew: list[CrewOut] = []
    seasons: list[SeasonOut] = []
    audio_languages: list[str] = []
    subtitle_languages: list[str] = []
    external_ids: dict[str, str] = {}
    attribution: list[str] = []


class CatalogPage(BaseModel):
    items: list[TitleCard]
    page: int = 1
    total_pages: int = 1
    degraded: bool = False  # a provider failed / is unconfigured; results may be partial or cached
    message: str | None = None


class EpisodeOut(BaseModel):
    id: uuid.UUID
    season: int
    number: int
    name: str | None = None
    overview: str | None = None
    air_date: date | None = None
    runtime_minutes: int | None = None
    still_url: str | None = None
    playable: bool = False


class ExternalOption(BaseModel):
    provider: str
    kind: Literal["free", "subscription", "rent", "buy"]
    label: str
    web_url: str | None = None
    price: float | None = None
    format: str | None = None


class AvailabilityOut(BaseModel):
    country: str
    viewer_country: str | None = None
    direct: DirectAccess | None = None
    direct_unavailable_reason: str | None = None
    external: list[ExternalOption] = []
    degraded: bool = False
    attribution: list[str] = []


# ---------- watchlist / progress ----------
class WatchlistIn(BaseModel):
    kind: Literal["watchlist", "favorite"] = "watchlist"


class RatingIn(BaseModel):
    value: Literal[-1, 1, 2]  # down, up, love


class RatingOut(BaseModel):
    value: int | None = None


class ProgressIn(BaseModel):
    title_id: uuid.UUID
    episode_id: uuid.UUID | None = None
    position_seconds: int = Field(ge=0, le=60 * 60 * 24)
    duration_seconds: int = Field(ge=0, le=60 * 60 * 24)


class ProgressOut(BaseModel):
    id: uuid.UUID
    title: TitleCard
    episode_id: uuid.UUID | None = None
    episode_label: str | None = None
    position_seconds: int
    duration_seconds: int
    completed: bool
    updated_at: datetime


# ---------- playback ----------
class PlaybackIn(BaseModel):
    title_id: uuid.UUID
    episode_id: uuid.UUID | None = None


class SubtitleOut(BaseModel):
    lang: str
    label: str
    url: str


class PlaybackOut(BaseModel):
    session_id: uuid.UUID
    episode_id: uuid.UUID | None = None  # echoed so the client can verify it got the episode it asked for
    expires_at: datetime
    kind: str
    url: str
    subtitles: list[SubtitleOut] = []
    audio_languages: list[str] = []
    resume_position_seconds: int = 0
    progress_interval_seconds: int = 15
    next_episode_id: uuid.UUID | None = None
    previous_episode_id: uuid.UUID | None = None
    title: TitleCard


# ---------- admin ----------
def _https_only(v: str) -> str:
    s = get_settings()
    if v.startswith("https://") or (not s.is_prod and v.startswith("http://localhost")):
        return v
    raise ValueError("URL must use https")


class AdminTitleIn(BaseModel):
    type: Literal["movie", "series"]
    name: str = Field(min_length=1, max_length=300)
    synopsis: str | None = None
    release_date: date | None = None
    runtime_minutes: int | None = Field(default=None, ge=0, le=1000)
    original_language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")
    genres: list[str] = []
    poster_url: str | None = None
    backdrop_url: str | None = None
    age_rating: str | None = Field(default=None, max_length=16)
    is_kids_safe: bool = False
    status: Literal["draft", "published", "archived"] = "draft"

    @field_validator("poster_url", "backdrop_url")
    @classmethod
    def _u(cls, v):
        return _https_only(v) if v else v


class AdminTitlePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    synopsis: str | None = None
    release_date: date | None = None
    runtime_minutes: int | None = Field(default=None, ge=0, le=1000)
    original_language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")
    genres: list[str] | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    age_rating: str | None = None
    is_kids_safe: bool | None = None
    status: Literal["draft", "published", "archived"] | None = None

    @field_validator("poster_url", "backdrop_url")
    @classmethod
    def _u(cls, v):
        return _https_only(v) if v else v


class ImportIn(BaseModel):
    provider: Literal["tmdb", "archive"]
    external_id: str = Field(min_length=1, max_length=100)
    type: Literal["movie", "series"] = "movie"


class Subtitle(BaseModel):
    lang: str = Field(pattern=r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")
    label: str = Field(max_length=60)
    url: str

    @field_validator("url")
    @classmethod
    def _u(cls, v):
        return _https_only(v)


class AssetIn(BaseModel):
    title_id: uuid.UUID
    episode_id: uuid.UUID | None = None
    kind: Literal["hls", "dash", "mp4", "embed"]
    url: str = Field(max_length=1000)
    requires_signing: bool = False
    audio_languages: list[str] = []
    subtitles: list[Subtitle] = []
    is_active: bool = True

    @field_validator("url")
    @classmethod
    def _u(cls, v):
        return _https_only(v)


class AssetPatch(BaseModel):
    url: str | None = Field(default=None, max_length=1000)
    requires_signing: bool | None = None
    audio_languages: list[str] | None = None
    subtitles: list[Subtitle] | None = None
    is_active: bool | None = None

    @field_validator("url")
    @classmethod
    def _u(cls, v):
        return _https_only(v) if v else v


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title_id: uuid.UUID
    episode_id: uuid.UUID | None
    kind: str
    url: str
    requires_signing: bool
    audio_languages: list | None
    subtitles: list | None
    is_active: bool


def _norm_territories(v):
    out = []
    for t in v:
        t = t.strip().upper()
        if t != "*" and not (len(t) == 2 and t.isalpha()):
            raise ValueError("territories must be '*' or ISO-3166 alpha-2 codes")
        out.append(t)
    return out


class RightIn(BaseModel):
    title_id: uuid.UUID
    license_type: Literal["public_domain", "creative_commons", "owned", "licensed", "unknown"]
    territories: list[str] = Field(default=["*"], min_length=1)
    entitlement: Literal["registered", "premium"] = "registered"
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    evidence_url: str | None = Field(default=None, max_length=1000)
    notes: str | None = None

    @field_validator("territories")
    @classmethod
    def _t(cls, v):
        return _norm_territories(v)


class RightPatch(BaseModel):
    license_type: Literal["public_domain", "creative_commons", "owned", "licensed", "unknown"] | None = None
    territories: list[str] | None = None
    entitlement: Literal["registered", "premium"] | None = None
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    evidence_url: str | None = None
    notes: str | None = None
    status: Literal["unverified", "rejected", "revoked"] | None = None  # verification has its own endpoint

    @field_validator("territories")
    @classmethod
    def _t(cls, v):
        return _norm_territories(v) if v else v


class RightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title_id: uuid.UUID
    license_type: str
    status: str
    territories: list
    entitlement: str
    starts_at: datetime | None
    expires_at: datetime | None
    evidence_url: str | None
    notes: str | None
    source: str
    verified_at: datetime | None


class PlanOut(BaseModel):
    code: str
    name: str
    has_ads: bool
    premium_titles: bool
    max_streams: int = 1
    price: dict | None = None  # {currency, amount_cents} for the viewer's country, null when unpriced
    purchasable: bool = False
    providers: list[str] = []  # which gateways can sell this plan here: "stripe", "razorpay"


class PlansOut(BaseModel):
    enabled: bool  # false until Stripe or Razorpay is configured
    plans: list[PlanOut]
    prepaid_days: int = 30  # length of a "pay once" purchase
    razorpay_key_id: str | None = None  # public Checkout key (rzp_test_/rzp_live_); never the secret


class RazorpaySubscribeIn(BaseModel):
    plan_code: Literal["ads", "standard", "premium"]


class RazorpaySubscribeOut(BaseModel):
    subscription_id: str
    key_id: str
    name: str
    email: str


class RazorpayVerifyIn(BaseModel):
    razorpay_payment_id: str = Field(max_length=64)
    razorpay_subscription_id: str = Field(max_length=64)
    razorpay_signature: str = Field(max_length=128)


class CheckoutIn(BaseModel):
    plan_code: Literal["ads", "standard", "premium"]


class UrlOut(BaseModel):
    url: str


class SubscriptionOut(BaseModel):
    plan_code: str
    plan_name: str
    status: str  # none | trialing | active | past_due | cancelled | expired
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    can_manage: bool = False


class MarkerIn(BaseModel):
    title_id: uuid.UUID
    episode_id: uuid.UUID | None = None  # required for series, absent for movies
    kind: Literal["intro", "recap", "credits"]
    start_s: int = Field(ge=0, le=60 * 60 * 24)
    end_s: int = Field(ge=1, le=60 * 60 * 24)


class MarkerOut(BaseModel):
    id: uuid.UUID
    episode_id: uuid.UUID | None = None
    kind: str
    start_s: int
    end_s: int


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=128)


class DeleteAccountIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class ChangePlanIn(BaseModel):
    plan_code: Literal["ads", "standard", "premium"]


class InvoiceOut(BaseModel):
    id: str
    number: str | None = None
    created: datetime
    total_cents: int
    currency: str
    status: str  # draft | open | paid | uncollectible | void
    url: str | None = None  # Stripe's hosted invoice page


class UserAdminPatch(BaseModel):
    plan: Literal["free", "premium"] | None = None
    is_active: bool | None = None


class FeaturedIn(BaseModel):
    title_id: uuid.UUID
    country: str = Field(default="*", pattern=r"^(\*|[A-Za-z]{2})$")
    position: int = Field(default=0, ge=0, le=100)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class FeaturedOut(BaseModel):
    id: uuid.UUID
    country: str
    position: int
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    title: TitleCard


class PlaybackReportIn(BaseModel):
    title_id: uuid.UUID
    episode_id: uuid.UUID | None = None
    kind: Literal["no_video", "no_sound", "buffering", "out_of_sync", "subtitles", "other"]
    note: str | None = Field(default=None, max_length=500)
    position_seconds: int | None = Field(default=None, ge=0, le=86400)


class RazorpayOrderOut(BaseModel):
    order_id: str
    amount: int
    currency: str
    key_id: str
    name: str
    email: str


class RazorpayOrderVerifyIn(BaseModel):
    razorpay_order_id: str = Field(max_length=64)
    razorpay_payment_id: str = Field(max_length=64)
    razorpay_signature: str = Field(max_length=128)
