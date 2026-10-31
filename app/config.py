import os
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=os.getenv("ENV_FILE", ".env"), extra="ignore", env_ignore_empty=True)

    env: str = "development"  # development | production | test
    database_url: str = "postgresql+psycopg://ott:ott@localhost:5432/ott"
    redis_url: str = ""

    # --- web / security ---
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    frontend_url: str = "http://localhost:5173"
    cookie_secure: bool | None = None  # default: True in production
    cookie_domain: str = ""
    session_ttl_hours: int = 24 * 14
    trust_proxy: bool = False
    country_header: str = ""  # e.g. CF-IPCountry; trusted only behind your CDN
    default_country: str = "US"  # fallback when no trusted country signal exists
    max_body_bytes: int = 256 * 1024
    enable_docs: bool = True
    metrics_token: str = ""
    require_email_verification: bool = True
    max_profiles: int = 5

    # --- mail ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "OTT Platform <no-reply@localhost>"

    # --- providers ---
    tmdb_read_token: str = ""  # v4 "API Read Access Token" (preferred)
    tmdb_api_key: str = ""  # v3 key fallback
    tmdb_image_base: str = "https://image.tmdb.org/t/p/"
    watchmode_api_key: str = ""
    archive_enabled: bool = True
    youtube_api_key: str = ""  # YouTube Data API v3 key from your own Google Cloud project; blank = no YouTube playback
    youtube_cache_s: int = 24 * 3600  # search.list costs 100 of the 10,000 daily units: keep answers a day
    google_client_id: str = ""
    google_client_secret: str = ""
    google_project_id: str = ""
    demo_sample_video: bool = False  # development only: give titles with no stream a public sample video
    extra_providers: Annotated[list[str], NoDecode] = []  # "package.module:ClassName"
    provider_timeout_s: float = 8.0
    provider_retries: int = 2

    # --- cache TTLs (seconds). Respect each provider's terms before raising these. ---
    ttl_lists: int = 3600
    ttl_details: int = 24 * 3600
    ttl_search: int = 900
    ttl_static: int = 7 * 24 * 3600
    ttl_availability: int = 12 * 3600
    stale_grace: int = 24 * 3600  # serve stale data this long when a provider fails
    details_refresh_days: int = 7

    # --- playback ---
    playback_session_minutes: int = 240
    embed_allowed_hosts: Annotated[list[str], NoDecode] = ["archive.org", "www.youtube-nocookie.com"]
    cdn_signing_secret: str = ""
    cdn_signing_ttl_s: int = 3600
    progress_min_delta_s: int = 5

    # --- video processing (see services/transcode.py) ---
    media_storage_dir: str = "media"  # holds incoming/ (admin drops sources here) and hls/<job id>/ (outputs)
    media_public_base: str = "/vod"  # URL prefix the web tier maps to <media_storage_dir>/hls
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    transcode_preset: str = "veryfast"
    transcode_max_attempts: int = 3
    transcode_lease_s: int = 7200  # a job "processing" longer than this is presumed orphaned by a dead worker
    transcode_timeout_s: int = 6 * 3600

    # --- billing (Stripe). Leave the secret blank to run without paid plans. Use test-mode keys until you launch. ---
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_api_base: str = "https://api.stripe.com/v1"
    stripe_webhook_tolerance_s: int = 300

    # --- billing (Razorpay). Blank key = Razorpay off. Use rzp_test_ keys until you launch. ---
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_api_base: str = "https://api.razorpay.com/v1"
    razorpay_total_count: int = 120  # billing cycles a new AutoPay mandate covers (monthly -> 10 years)

    # --- retention (days) ---
    retain_playback_sessions_days: int = 90
    retain_audit_days: int = 365

    @field_validator("cors_origins", "extra_providers", "embed_allowed_hosts", mode="before")
    @classmethod
    def _split(cls, v):
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @property
    def is_prod(self) -> bool:
        return self.env == "production"

    @property
    def secure_cookies(self) -> bool:
        return self.is_prod if self.cookie_secure is None else self.cookie_secure


_WEAK_DB_PASSWORDS = {"ott", "postgres", "password", "2205", "admin", "root", "changeme", "secret", "123456"}


def production_problems(s: "Settings") -> tuple[list[str], list[str]]:
    """(fatal, warnings) for ENV=production. Fatal items would put real users or credentials at risk, so the API refuses to
    start; warnings are logged at startup."""
    from urllib.parse import urlsplit

    fatal: list[str] = []
    warn: list[str] = []
    try:
        pw = urlsplit(s.database_url.replace("+psycopg", "")).password or ""
    except ValueError:
        pw = ""
    if s.database_url.startswith("postgresql") and pw.lower() in _WEAK_DB_PASSWORDS:
        fatal.append("DATABASE_URL uses a well-known default password; set a strong POSTGRES_PASSWORD")
    if any(o == "*" or not o.startswith("https://") for o in s.cors_origins):
        fatal.append("CORS_ORIGINS must list exact https:// origins (no '*', no http://, no localhost)")
    if not s.frontend_url.startswith("https://"):
        fatal.append("FRONTEND_URL must be https:// (it is used in verification, reset and checkout links)")
    if s.cookie_secure is False:
        fatal.append("COOKIE_SECURE=false would send session cookies over plain http")
    if s.demo_sample_video:
        fatal.append("DEMO_SAMPLE_VIDEO is a development-only switch")
    if not s.redis_url:
        warn.append("REDIS_URL is empty: rate limits and caches are per worker process, not shared")
    if not s.country_header:
        warn.append("COUNTRY_HEADER is empty: territory rights fall back to DEFAULT_COUNTRY for every viewer")
    if s.require_email_verification and not s.smtp_host:
        warn.append("SMTP_HOST is empty: verification and password-reset emails cannot be delivered")
    if s.enable_docs:
        warn.append("ENABLE_DOCS=true exposes the API schema publicly")
    if s.razorpay_key_secret and not s.razorpay_webhook_secret:
        fatal.append("RAZORPAY_KEY_SECRET is set but RAZORPAY_WEBHOOK_SECRET is empty: renewals and failures would never arrive")
    if s.razorpay_key_id.startswith("rzp_test_"):
        warn.append("Razorpay is using TEST keys in production")
    if not s.stripe_webhook_secret and s.stripe_secret_key:
        fatal.append("STRIPE_SECRET_KEY is set but STRIPE_WEBHOOK_SECRET is empty: subscription events could not be verified")
    return fatal, warn


@lru_cache
def get_settings() -> Settings:
    return Settings()
