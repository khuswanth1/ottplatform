"""Relational schema. Portable types only (Uuid/JSON) so PostgreSQL is the target and SQLite works in tests."""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, Uuid, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


def _pk():
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _ts(**kw):
    return mapped_column(DateTime(timezone=True), **kw)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")  # user | admin
    plan: Mapped[str] = mapped_column(String(16), default="free")  # free | premium (entitlements)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified_at: Mapped[datetime | None] = _ts(nullable=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = _ts(nullable=True)
    created_at: Mapped[datetime] = _ts(default=now)
    profiles: Mapped[list["Profile"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    __table_args__ = (CheckConstraint("role in ('user','admin')", name="ck_users_role"),)


class EmailToken(Base):
    __tablename__ = "email_tokens"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(16))  # verify | reset
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = _ts()
    used_at: Mapped[datetime | None] = _ts(nullable=True)


class AuthSession(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts(default=now)
    last_seen_at: Mapped[datetime] = _ts(default=now)
    expires_at: Mapped[datetime] = _ts(index=True)
    revoked_at: Mapped[datetime | None] = _ts(nullable=True)
    unlocked_profile_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)  # the one PIN-locked profile opened in this session
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    avatar: Mapped[str] = mapped_column(String(32), default="avatar-1")
    language: Mapped[str] = mapped_column(String(8), default="en")  # preferred content/UI language
    is_kids: Mapped[bool] = mapped_column(Boolean, default=False)  # always == (maturity_level == "kids")
    maturity_level: Mapped[str] = mapped_column(String(8), default="all")  # kids | 7+ | 13+ | all
    pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pin_failed: Mapped[int] = mapped_column(Integer, default=0)
    pin_locked_until: Mapped[datetime | None] = _ts(nullable=True)
    created_at: Mapped[datetime] = _ts(default=now)
    user: Mapped[User] = relationship(back_populates="profiles")

    @property
    def has_pin(self) -> bool:
        return self.pin_hash is not None

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_profile_user_name"),
                      CheckConstraint("maturity_level in ('kids','7+','13+','all')", name="ck_profiles_maturity"))


class Language(Base):
    __tablename__ = "languages"
    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    english_name: Mapped[str] = mapped_column(String(80), default="")


class Genre(Base):
    __tablename__ = "genres"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)


class Title(Base):
    __tablename__ = "titles"
    id: Mapped[uuid.UUID] = _pk()
    type: Mapped[str] = mapped_column(String(16))  # movie | series
    name: Mapped[str] = mapped_column(String(300))
    norm_name: Mapped[str] = mapped_column(String(300), index=True)  # for de-duplication
    original_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    synopsis: Mapped[str | None] = mapped_column(Text, nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_language: Mapped[str | None] = mapped_column(ForeignKey("languages.code"), nullable=True)
    poster_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    backdrop_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    vote_average: Mapped[float | None] = mapped_column(Float, nullable=True)
    popularity: Mapped[float | None] = mapped_column(Float, nullable=True)
    age_rating: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_kids_safe: Mapped[bool] = mapped_column(Boolean, default=False)
    audio_languages: Mapped[list | None] = mapped_column(JSON, nullable=True)  # from provider metadata
    subtitle_languages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="published")  # draft | published | archived
    source: Mapped[str] = mapped_column(String(24), default="tmdb")  # first provider that created it
    metadata_synced_at: Mapped[datetime | None] = _ts(nullable=True)
    details_synced_at: Mapped[datetime | None] = _ts(nullable=True)
    created_at: Mapped[datetime] = _ts(default=now, index=True)
    updated_at: Mapped[datetime] = _ts(default=now, onupdate=now)

    genres: Mapped[list[Genre]] = relationship(secondary="title_genres", lazy="selectin")
    external_ids: Mapped[list["TitleExternalId"]] = relationship(
        back_populates="title", cascade="all, delete-orphan", lazy="selectin"
    )
    cast: Mapped[list["CastMember"]] = relationship(
        cascade="all, delete-orphan", order_by="CastMember.position", lazy="select"
    )
    crew: Mapped[list["CrewMember"]] = relationship(
        cascade="all, delete-orphan", order_by="CrewMember.position", lazy="select"
    )
    seasons: Mapped[list["Season"]] = relationship(
        cascade="all, delete-orphan", order_by="Season.number", lazy="select"
    )
    __table_args__ = (
        CheckConstraint("type in ('movie','series')", name="ck_titles_type"),
        CheckConstraint("status in ('draft','published','archived')", name="ck_titles_status"),
        Index("ix_titles_listing", "status", "type", "popularity"),
        Index("ix_titles_lang_year", "original_language", "year"),
    )


class TitleGenre(Base):
    __tablename__ = "title_genres"
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), primary_key=True)
    genre_id: Mapped[int] = mapped_column(ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True, index=True)


class TitleExternalId(Base):
    __tablename__ = "title_external_ids"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(24))  # tmdb | imdb | watchmode | archive | ...
    external_id: Mapped[str] = mapped_column(String(100))
    title: Mapped[Title] = relationship(back_populates="external_ids")
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_external_provider_id"),)


class CastMember(Base):
    __tablename__ = "title_cast"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    person_name: Mapped[str] = mapped_column(String(200), index=True)
    character: Mapped[str | None] = mapped_column(String(300), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    external_person_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    profile_path: Mapped[str | None] = mapped_column(String(500), nullable=True)


class CrewMember(Base):
    __tablename__ = "title_crew"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    person_name: Mapped[str] = mapped_column(String(200), index=True)
    job: Mapped[str | None] = mapped_column(String(200), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    external_person_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    profile_path: Mapped[str | None] = mapped_column(String(500), nullable=True)



class Season(Base):
    __tablename__ = "seasons"
    id: Mapped[uuid.UUID] = _pk()
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    air_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    poster_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    episode_count: Mapped[int] = mapped_column(Integer, default=0)
    episodes_synced_at: Mapped[datetime | None] = _ts(nullable=True)
    __table_args__ = (UniqueConstraint("title_id", "number", name="uq_season_title_number"),)


class Episode(Base):
    __tablename__ = "episodes"
    id: Mapped[uuid.UUID] = _pk()
    season_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), index=True)
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    air_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    still_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    __table_args__ = (UniqueConstraint("season_id", "number", name="uq_episode_season_number"),)


class MediaAsset(Base):
    """An approved, playable source. Only rows an admin created (after rights review) can ever be played."""
    __tablename__ = "media_assets"
    id: Mapped[uuid.UUID] = _pk()
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(8))  # hls | dash | mp4 | embed
    url: Mapped[str] = mapped_column(String(1000))
    requires_signing: Mapped[bool] = mapped_column(Boolean, default=False)
    audio_languages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    subtitles: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{lang,label,url}]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = _ts(default=now)
    __table_args__ = (CheckConstraint("kind in ('hls','dash','mp4','embed')", name="ck_assets_kind"),)


class TitleRight(Base):
    __tablename__ = "title_rights"
    id: Mapped[uuid.UUID] = _pk()
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    license_type: Mapped[str] = mapped_column(String(24))  # public_domain | creative_commons | owned | licensed
    status: Mapped[str] = mapped_column(String(12), default="unverified")  # unverified|verified|rejected|revoked
    territories: Mapped[list] = mapped_column(JSON, default=list)  # ["*"] worldwide, or ISO-3166 alpha-2 codes
    entitlement: Mapped[str] = mapped_column(String(12), default="registered")  # registered | premium
    starts_at: Mapped[datetime | None] = _ts(nullable=True)
    expires_at: Mapped[datetime | None] = _ts(nullable=True)
    evidence_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="admin")
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verified_at: Mapped[datetime | None] = _ts(nullable=True)
    __table_args__ = (
        CheckConstraint("status in ('unverified','verified','rejected','revoked')", name="ck_rights_status"),
        CheckConstraint("entitlement in ('registered','premium')", name="ck_rights_entitlement"),
    )


class TitleAvailability(Base):
    """Country-specific external viewing options (Watchmode / TMDB watch-providers). Links only, never streams."""
    __tablename__ = "title_availability"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"))
    country: Mapped[str] = mapped_column(String(2))
    source: Mapped[str] = mapped_column(String(24))
    provider_name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(12))  # free | subscription | rent | buy
    web_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    format: Mapped[str | None] = mapped_column(String(12), nullable=True)
    __table_args__ = (Index("ix_avail_title_country", "title_id", "country"),)


class AvailabilityFetch(Base):
    __tablename__ = "availability_fetches"
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), primary_key=True)
    country: Mapped[str] = mapped_column(String(2), primary_key=True)
    fetched_at: Mapped[datetime] = _ts(default=now)


class WatchlistItem(Base):
    __tablename__ = "watchlists"
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), primary_key=True)  # watchlist | favorite
    added_at: Mapped[datetime] = _ts(default=now, index=True)
    __table_args__ = (CheckConstraint("kind in ('watchlist','favorite')", name="ck_watchlist_kind"),)


class TitleRating(Base):
    __tablename__ = "title_ratings"
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), primary_key=True, index=True)
    value: Mapped[int] = mapped_column(Integer)  # -1 down, 1 up, 2 love
    rated_at: Mapped[datetime] = _ts(default=now)
    __table_args__ = (CheckConstraint("value in (-1, 1, 2)", name="ck_title_ratings_value"),)


class WatchProgress(Base):
    __tablename__ = "watch_progress"
    id: Mapped[uuid.UUID] = _pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"))
    episode_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True)
    episode_key: Mapped[str] = mapped_column(String(36), default="-")  # episode id or "-" (NULL-safe uniqueness)
    position_seconds: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden_at: Mapped[datetime | None] = _ts(nullable=True)  # removed from viewing activity; kept so resume data survives
    updated_at: Mapped[datetime] = _ts(default=now, index=True)
    __table_args__ = (
        UniqueConstraint("profile_id", "title_id", "episode_key", name="uq_progress_item"),
        Index("ix_progress_profile_updated", "profile_id", "updated_at"),
    )


class TitleMarker(Base):
    """A stretch of a film or episode the player can offer to skip. Entered by an admin; nothing is detected automatically."""
    __tablename__ = "title_markers"
    id: Mapped[uuid.UUID] = _pk()
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True)
    episode_key: Mapped[str] = mapped_column(String(36), default="-")  # episode id or "-" (NULL-safe uniqueness)
    kind: Mapped[str] = mapped_column(String(8))  # intro | recap | credits
    start_s: Mapped[int] = mapped_column(Integer)
    end_s: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("title_id", "episode_key", "kind", name="uq_marker"),
        CheckConstraint("kind in ('intro','recap','credits')", name="ck_markers_kind"),
        CheckConstraint("start_s >= 0 and end_s > start_s", name="ck_markers_order"),
    )


class Reminder(Base):
    __tablename__ = "reminders"
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = _ts(default=now)
    notified_at: Mapped[datetime | None] = _ts(nullable=True)  # set when the release notification was created


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = _pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24))  # reminder_released | new_episode | new_in_list
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"))
    episode_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True)
    episode_key: Mapped[str] = mapped_column(String(36), default="-")  # episode id or "-" (NULL-safe uniqueness)
    created_at: Mapped[datetime] = _ts(default=now)
    read_at: Mapped[datetime | None] = _ts(nullable=True)
    __table_args__ = (
        UniqueConstraint("profile_id", "kind", "title_id", "episode_key", name="uq_notification_dedupe"),
        CheckConstraint("kind in ('reminder_released','new_episode','new_in_list')", name="ck_notifications_kind"),
        Index("ix_notifications_profile_created", "profile_id", "created_at"),
    )


class PlaybackSession(Base):
    __tablename__ = "playback_sessions"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True)
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"))
    episode_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    issued_at: Mapped[datetime] = _ts(default=now, index=True)
    last_seen_at: Mapped[datetime] = _ts(default=now)  # last heartbeat; a stream counts toward the plan limit while this is recent
    expires_at: Mapped[datetime] = _ts()
    ended_at: Mapped[datetime | None] = _ts(nullable=True)
    __table_args__ = (Index("ix_playback_sessions_live", "user_id", "last_seen_at"),)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _ts(default=now, index=True)


class FeaturedTitle(Base):
    """Admin-curated billboard entries for the home page (empty list -> the UI falls back to trending)."""
    __tablename__ = "featured_titles"
    id: Mapped[uuid.UUID] = _pk()
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"))
    country: Mapped[str] = mapped_column(String(2), default="*")  # ISO code or "*" for everywhere
    position: Mapped[int] = mapped_column(Integer, default=0)
    starts_at: Mapped[datetime | None] = _ts(nullable=True)
    ends_at: Mapped[datetime | None] = _ts(nullable=True)
    created_at: Mapped[datetime] = _ts(default=now)
    __table_args__ = (UniqueConstraint("title_id", "country", name="uq_featured_title_country"),
                      Index("ix_featured_country_position", "country", "position"))


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(String(16), unique=True)  # free | ads | standard | premium
    name: Mapped[str] = mapped_column(String(40))
    has_ads: Mapped[bool] = mapped_column(Boolean, default=False)
    max_streams: Mapped[int] = mapped_column(Integer, default=1)  # screens at once, enforced when playback starts and on heartbeat
    max_height: Mapped[int] = mapped_column(Integer, default=1080)  # not enforced yet
    entitlement: Mapped[str] = mapped_column(String(16), default="registered")  # premium -> users.plan "premium"
    sort: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (CheckConstraint("code in ('free','ads','standard','premium')", name="ck_plans_code"),
                      CheckConstraint("entitlement in ('registered','premium')", name="ck_plans_entitlement"))


class PlanPrice(Base):
    __tablename__ = "plan_prices"
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True)
    country: Mapped[str] = mapped_column(String(2), primary_key=True)  # ISO code, or "*" as the fallback price
    currency: Mapped[str] = mapped_column(String(3))
    amount_cents: Mapped[int] = mapped_column(Integer)
    stripe_price_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    razorpay_plan_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # INR rows only
    __table_args__ = (CheckConstraint("amount_cents >= 0", name="ck_plan_prices_amount"),)


LIVE_STATUSES = ("trialing", "active", "past_due")


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(12))
    provider: Mapped[str] = mapped_column(String(10), default="stripe")  # stripe | razorpay
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    # one-time ("pay once") Razorpay purchases have no subscription id: they hold this payment id instead (also makes a
    # replayed verify call idempotent) and end on current_period_end via the worker's expire_prepaid job
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    current_period_end: Mapped[datetime | None] = _ts(nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    event_ts: Mapped[int] = mapped_column(Integer, default=0)  # created time of the newest Stripe event applied
    created_at: Mapped[datetime] = _ts(default=now)
    updated_at: Mapped[datetime] = _ts(default=now, onupdate=now)
    plan: Mapped[Plan] = relationship()
    __table_args__ = (
        CheckConstraint("status in ('trialing','active','past_due','cancelled','expired')", name="ck_subscriptions_status"),
        CheckConstraint("provider in ('stripe','razorpay')", name="ck_subscriptions_provider"),
        # one live subscription per user, enforced by the database
        Index("uq_subscriptions_one_live", "user_id", unique=True,
              postgresql_where=text("status in ('trialing','active','past_due')"),
              sqlite_where=text("status in ('trialing','active','past_due')")),
    )


class StripeEvent(Base):
    """Webhook idempotency: the event id is the primary key; it is inserted in the same transaction as its effects."""
    __tablename__ = "stripe_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = _ts(default=now)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class PlaybackReport(Base):
    """A viewer's "something is wrong with playback" note. Read by admins; deleted with the account."""
    __tablename__ = "playback_reports"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    position_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)  # open | resolved
    created_at: Mapped[datetime] = _ts(default=now)
    resolved_at: Mapped[datetime | None] = _ts(nullable=True)
    __table_args__ = (
        CheckConstraint("status in ('open', 'resolved')", name="ck_playback_reports_status"),
        CheckConstraint("kind in ('no_video', 'no_sound', 'buffering', 'out_of_sync', 'subtitles', 'other')",
                        name="ck_playback_reports_kind"),
    )


class MediaJob(Base):
    """One source file to turn into an adaptive HLS ladder. Claimed by the transcode worker, never run inside a request."""
    __tablename__ = "media_jobs"
    id: Mapped[uuid.UUID] = _pk()
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True)
    episode_key: Mapped[str] = mapped_column(String(36), default="-")  # episode id or "-" (NULL-safe uniqueness)
    source: Mapped[str] = mapped_column(String(300))  # path under <media_storage_dir>/incoming
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued | processing | ready | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    locked_at: Mapped[datetime | None] = _ts(nullable=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True)
    renditions: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{height, bitrate_k}] actually produced
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = _ts(default=now)
    updated_at: Mapped[datetime] = _ts(default=now, onupdate=now)
    finished_at: Mapped[datetime | None] = _ts(nullable=True)
    __table_args__ = (
        CheckConstraint("status in ('queued','processing','ready','failed')", name="ck_media_jobs_status"),
        # a title/episode can have only one unfinished job, so a double click cannot queue the same work twice
        Index("uq_media_jobs_one_active", "title_id", "episode_key", unique=True,
              postgresql_where=text("status in ('queued','processing')"),
              sqlite_where=text("status in ('queued','processing')")),
        Index("ix_media_jobs_queue", "status", "created_at"),
    )
