# 🎬 OTT Platform — Backend API Service

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0+-D71F00?style=flat&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-336791?style=flat&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7+-DC382D?style=flat&logo=redis&logoColor=white)](https://redis.io/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat&logo=docker&logoColor=white)](https://www.docker.com/)
[![Alembic](https://img.shields.io/badge/Alembic-Migrations-gray?style=flat)](https://alembic.sqlalchemy.org/)

A production-grade, secure, and extensible backend API service for an **Over-The-Top (OTT) streaming platform**. It handles user authentication with multi-profile support, catalog aggregation (TMDB, Watchmode, Internet Archive), territory licensing & geo-restrictions, playback session provisioning with HMAC CDN URL signing, watchlist management, watch progress tracking, and an admin content management system (CMS).

---

## 📑 Table of Contents

- [Key Features](#-key-features)
- [Architecture & Tech Stack](#-architecture--tech-stack)
- [Project Directory Structure](#-project-directory-structure)
- [Prerequisites](#-prerequisites)
- [Quickstart with Docker (Recommended)](#-quickstart-with-docker-recommended)
- [Local Development Setup (Manual)](#-local-development-setup-manual)
- [Admin User Bootstrap (CLI)](#-admin-user-bootstrap-cli)
- [Configuration Reference (.env)](#-configuration-reference-env)
- [External Providers Integration](#-external-providers-integration)
- [API Architecture & Endpoints](#-api-architecture--endpoints)
- [Authentication & CSRF Security Flow](#-authentication--csrf-security-flow)
- [Database Migrations (Alembic)](#-database-migrations-alembic)
- [Running Automated Tests](#-running-automated-tests)
- [Production Deployment & Security Checklist](#-production-deployment--security-checklist)

---

## ✨ Key Features

### 🔐 Authentication & Profile Management
- **Enterprise-Grade Security**: Secure HTTP-only cookie-based sessions with Argon2id password hashing (OWASP parameters) and brute-force lockout protection (5 failed attempts).
- **CSRF Defense**: Double-submit CSRF cookie + header (`X-CSRF-Token`) verification on all state-mutating requests.
- **Account Verification**: Email verification and password reset token workflows (printed to console in local dev, or sent via SMTP in production).
- **Multi-Profile Support**: Up to 5 user profiles per account with independent watchlists, avatars, watch progress, and a dedicated **Kids Mode** filter.

### 🎥 Catalog & Discovery Engine
- **Aggregated Metadata**: Upstream adapters for **TMDB** (movies/shows, cast, crew, genres, posters, backdrops) and **Watchmode** (availability by region/provider).
- **Public Domain Streaming**: Built-in support for **Internet Archive** to search, index, and stream public domain movies directly.
- **Multi-Level Caching**: Redis-backed distributed cache with fallback to in-memory TTL caching and graceful serving of stale data during upstream provider outages.
- **Rich Browsing**: Faceted catalog filtering by genres, release year, original languages, maturity ratings, and full-text search.

### 🌍 Territory Rights & Geo-Fencing
- **License Windows**: Enforces territory licensing start and end dates and exclusivity agreements.
- **Geo-Blocking**: Enforces rights using trusted CDN geolocation headers (e.g., Cloudflare `CF-IPCountry`) or a configurable default country for local testing.

### ▶️ Playback & Streaming Engine
- **Playback Session Provisioning**: Time-limited playback session tokens (`/api/v1/playback/sessions`).
- **CDN HMAC URL Signing**: Automatic generation of tamper-proof signed URLs with expiration (`exp` and `sig` query params) for media assets requiring CDN signature verification.
- **Embed Filtering**: Whitelisted playback iframe domains (Internet Archive, YouTube Privacy-Enhanced).
- **Resume & Progress Tracking**: Real-time position tracking with debounce threshold and automatic "completed" marking at 90% completion.

### 🛠️ Admin CMS & Observability
- **Admin Endpoints**: Ingest titles from TMDB, search and import from Internet Archive, attach media assets (HLS, DASH, MP4), assign territory rights, and moderate users.
- **Audit Logging**: Structured audit logs capturing all administrative actions with actor ID, IP address, and payload diffs.
- **Health & Metrics**: Built-in `/healthz` liveness probe, `/readyz` dependency readiness probe (PostgreSQL + Redis + providers), and token-protected Prometheus `/metrics`.

---

## 🏗 Architecture & Tech Stack

```text
                           ┌───────────────────────────────┐
                           │      Web / Mobile Client      │
                           └───────────────┬───────────────┘
                                           │ HTTP/JSON (CORS, CSRF, Cookies)
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                FastAPI Backend                                   │
│                                                                                  │
│  [Middlewares]                                                                   │
│   ├── BodyLimit (Max payload size check)                                         │
│   ├── CORSMiddleware (Configured allowed origins)                                │
│   └── RequestGuard (X-Request-ID, nosniff, frame denial, metrics recorder)       │
│                                                                                  │
│  [Routers]                                                                       │
│   ├── /api/v1/auth         (Register, Login, Session, Reset Password)            │
│   ├── /api/v1/profiles     (Profile CRUD, Kids Mode)                             │
│   ├── /api/v1/catalog      (Browse, Home Feed, Search, Genres, Languages)        │
│   ├── /api/v1/titles       (Details, Availability, Episodes)                     │
│   ├── /api/v1/watchlist    (Per-Profile Saved Titles)                            │
│   ├── /api/v1/progress     (Playback Progress, Resume Points)                    │
│   ├── /api/v1/playback     (Session Tokens, Signed CDN URLs, Embed Validation)   │
│   └── /api/v1/admin        (Catalog Ingestion, Assets, Rights, Audit Logs)       │
│                                                                                  │
│  [Services & Adapters]                                                           │
│   ├── Provider Registry: TMDB, Watchmode, Internet Archive                       │
│   ├── Geo & Rights Verification (Country header check)                           │
│   └── Media URL Signer (HMAC-SHA256)                                             │
└───────────────────────┬──────────────────────────────┬───────────────────────────┘
                        │                              │
                        ▼                              ▼
             ┌─────────────────────┐        ┌─────────────────────┐
             │ PostgreSQL 16 (DB)  │        │   Redis 7 (Cache)   │
             │ SQLAlchemy 2.0 ORM  │        │ Shared TTL & Limits │
             └─────────────────────┘        └─────────────────────┘
```

| Component | Technology | Description |
| :--- | :--- | :--- |
| **API Framework** | FastAPI 0.115+ | High-performance asynchronous web framework |
| **Server** | Uvicorn 0.30+ | ASGI production server |
| **ORM** | SQLAlchemy 2.0 (psycopg 3) | Modern typed DB mapping & connection pooling |
| **Schema & Settings** | Pydantic v2 & Pydantic-Settings | Validation and environment configuration |
| **Database** | PostgreSQL 16+ | Relational storage for users, catalog, assets, rights |
| **Cache & Limiter** | Redis 7+ | Distributed caching, session rate limits |
| **Migrations** | Alembic 1.13+ | Database schema version control |
| **Security** | Argon2-cffi | Memory-hard password hashing |
| **HTTP Client** | HTTPX 0.27+ | Async HTTP client for provider communication |

---

## 📁 Project Directory Structure

```text
backend/
├── alembic/                    # Database migration scripts
│   ├── env.py                  # Alembic environment runner
│   ├── script.py.mako          # Migration template
│   └── versions/               # Schema revision history
│       └── 0001_initial_schema.py
├── app/                        # Main application package
│   ├── __init__.py
│   ├── main.py                 # FastAPI application factory & middlewares
│   ├── config.py               # Pydantic Settings & environment parsing
│   ├── db.py                   # SQLAlchemy engine & session setup
│   ├── deps.py                 # Dependency injection (Auth, CSRF, DB, Geo)
│   ├── models.py               # SQLAlchemy ORM models
│   ├── schemas.py              # Pydantic request/response models
│   ├── security.py             # Argon2 hashing, tokens, CDN signing
│   ├── cache.py                # Redis & in-memory cache layer
│   ├── ratelimit.py            # Sliding window rate limiter
│   ├── mailer.py               # Email dispatch (SMTP / Console dev)
│   ├── metrics.py              # Prometheus metrics collector
│   ├── retention.py            # Session & audit log data cleanup
│   ├── cli.py                  # CLI utility to bootstrap admin users
│   ├── providers/              # Metadata & streaming provider adapters
│   │   ├── base.py             # Abstract provider interface & HTTP client
│   │   ├── registry.py         # Provider registration & health
│   │   ├── tmdb.py             # TMDB API adapter
│   │   ├── watchmode.py        # Watchmode streaming availability
│   │   └── archive.py          # Internet Archive adapter
│   ├── routers/                # API route definitions
│   │   ├── admin.py            # Admin CMS, imports, rights, audit logs
│   │   ├── auth.py             # Authentication & password management
│   │   ├── catalog.py          # Catalog discovery, search, home feed
│   │   ├── playback.py         # Playback sessions & embed streams
│   │   ├── profiles.py         # Profile management
│   │   ├── progress.py         # Continue watching & progress tracking
│   │   ├── titles.py           # Title details & episodes
│   │   └── watchlist.py        # Saved titles per profile
│   └── services/               # Core business logic
│       ├── availability.py     # Aggregated stream availability
│       ├── catalog.py          # Catalog search & sync logic
│       └── rights.py           # Territory rights validation
├── tests/                      # Automated test suite
│   ├── conftest.py             # Test fixtures & mocks
│   ├── test_auth.py            # Authentication & session tests
│   ├── test_catalog.py         # Discovery & caching tests
│   ├── test_playback.py        # Stream provisioning & signing tests
│   ├── test_ownership.py       # Profile & account isolation tests
│   └── test_progress_admin.py  # Progress & admin operations tests
├── .env.example                # Sample environment variables
├── .env                        # Local development environment configuration
├── alembic.ini                 # Alembic configuration
├── docker-compose.yml          # Docker Compose orchestration
├── Dockerfile                  # Production container definition
├── requirements.txt            # Production dependencies
└── requirements-dev.txt        # Development & testing dependencies
```

---

## 📋 Prerequisites

Before setting up the project, make sure you have:

- **Python 3.12** or higher (verify with `python --version`)
- **Docker** and **Docker Compose** (verify with `docker compose version`)
- *(If running without Docker)*: Local instance of **PostgreSQL 16** and **Redis 7**

---

## 🚀 Quickstart for Windows (No Docker Required)

If you do not have Docker installed on Windows, you can start the entire backend immediately with one command:

```powershell
.\start.ps1
```

*(Or simply double-click `run.bat` in Windows File Explorer).*

This script automatically:
1. Runs database migrations (`alembic upgrade head`)
2. Starts the server on `http://localhost:8000`
3. Opens Swagger Docs at `http://localhost:8000/api/v1/docs`

---

## 🐳 Quickstart with Docker (Optional — Requires Docker Desktop)

If you have Docker Desktop installed on your system:

### 1. Start Services
Run all containers in detached mode:
```bash
docker compose up -d --build
```

Docker will:
1. Start `ott_postgres` on port `5432` with automatic health checks.
2. Start `ott_redis` on port `6379`.
3. Run `ott_migrate` to automatically apply all database migrations (`alembic upgrade head`).
4. Start `ott_backend` on `http://localhost:8000`.

### 3. Verify Health & Open Docs
Check that the API is running:
- **Interactive Swagger UI**: [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)
- **Liveness Probe**: [http://localhost:8000/healthz](http://localhost:8000/healthz)
- **Readiness Probe**: [http://localhost:8000/readyz](http://localhost:8000/readyz)

### 4. Create an Initial Admin User
Run the CLI bootstrap tool inside the running container:
```bash
docker compose exec api python -m app.cli create-admin admin@example.com
```
*You will be prompted to type and confirm a secure password (minimum 10 characters).*

### 5. Stop the Containers
```bash
docker compose down
```
*(To erase database volumes as well, use `docker compose down -v`)*

---

## 💻 Local Development Setup (Manual)

If you prefer to run the Python server directly on your host machine:

### ⚡ One-Command Windows Quick Start
You can launch the entire backend with a single command:
```powershell
.\start.ps1
```
*(Or simply double-click `run.bat` in File Explorer).*

---

### Manual Setup (Step-by-Step)

### 1. Create and Activate a Python Virtual Environment

**On Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```
*(If PowerShell displays a policy error, allow local scripts by running: `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`)*


**On Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements-dev.txt
```

### 3. Configure `.env`
Inspect and configure `.env`:
```ini
ENV=development
POSTGRES_USER=postgres
POSTGRES_PASSWORD=xyzy
POSTGRES_DB=ott
DATABASE_URL=postgresql+psycopg://postgres:change-me@localhost:5432/ott
REDIS_URL=redis://localhost:6379/0
COOKIE_SECURE=false
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
FRONTEND_URL=http://localhost:5173
```
> **Tip for rapid local testing without PostgreSQL:**
> You can set `DATABASE_URL=sqlite:///./ott.db` in `.env` to test with SQLite locally!

### 4. Run Database Migrations
Apply the initial schema:
```bash
alembic upgrade head
```

### 5. Create an Admin Account
```bash
python -m app.cli create-admin admin@example.com
```

### 6. Run the Development Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
The server will now be live at `http://localhost:8000` with hot-reload enabled.

---

## 👤 Admin User Bootstrap (CLI)

The application includes a built-in CLI tool to bootstrap an administrative account or promote an existing user to `admin`:

```bash
python -m app.cli create-admin <EMAIL>
```

**Example:**
```bash
python -m app.cli create-admin admin@ottplatform.local
Password: **********
Admin ready: admin@ottplatform.local
```

**Password Requirements:**
- Must be at least 10 characters long.
- Maximum 128 characters.
- Must not be a trivial sequence (e.g. `password123`, `qwertyuiop`).

---

## ⚙️ Configuration Reference (.env)

The application reads configuration through `pydantic-settings` from environment variables or the `.env` file:

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `ENV` | `string` | `development` | Environment mode (`development`, `production`, `test`). |
| `DATABASE_URL` | `string` | `postgresql+psycopg://postgres:change-me@localhost:5432/ott` | Database connection string using psycopg 3 driver. |
| `REDIS_URL` | `string` | `redis://localhost:6379/0` | Redis instance URL for distributed cache & rate limiting. |
| `CORS_ORIGINS` | `list` | `http://localhost:5173` | Comma-separated allowed frontend origins. |
| `FRONTEND_URL` | `string` | `http://localhost:5173` | Base URL used to build email verification / reset links. |
| `COOKIE_SECURE` | `bool` | `false` (dev) / `true` (prod) | Set `false` for plain HTTP local dev; `true` on HTTPS. |
| `COOKIE_DOMAIN` | `string` | `""` | Optional shared root cookie domain (e.g., `.example.com`). |
| `TRUST_PROXY` | `bool` | `false` | Enable when running behind a trusted reverse proxy (NGINX/Traefik/Cloudflare). |
| `COUNTRY_HEADER` | `string` | `""` | Header passed by CDN for geolocation (e.g. `CF-IPCountry`). |
| `DEFAULT_COUNTRY` | `string` | `US` | Fallback country code when no country header is found. |
| `REQUIRE_EMAIL_VERIFICATION` | `bool` | `false` (dev) / `true` (prod) | Whether unverified accounts are blocked from logging in. |
| `ENABLE_DOCS` | `bool` | `true` | Serves interactive Swagger UI at `/api/v1/docs`. |
| `METRICS_TOKEN` | `string` | `""` | Bearer token required to access `/metrics`. |
| `SMTP_HOST` | `string` | `""` | Outgoing SMTP server host. Leave empty in dev to print emails to console. |
| `SMTP_PORT` | `int` | `587` | SMTP port (typically 587 for STARTTLS). |
| `SMTP_USER` | `string` | `""` | SMTP authentication username. |
| `SMTP_PASSWORD` | `string` | `""` | SMTP authentication password. |
| `SMTP_FROM` | `string` | `OTT Platform <no-reply@localhost>` | Outgoing email sender name and address. |
| `TMDB_READ_TOKEN` | `string` | `""` | TMDB API Read Access Token (v4). |
| `TMDB_API_KEY` | `string` | `""` | Alternative TMDB v3 API key. |
| `WATCHMODE_API_KEY` | `string` | `""` | Watchmode API key for streaming provider availability. |
| `ARCHIVE_ENABLED` | `bool` | `true` | Enables Internet Archive public domain integration. |
| `EMBED_ALLOWED_HOSTS` | `list` | `archive.org,www.youtube-nocookie.com` | Allowed domains for iframe embeds. |
| `CDN_SIGNING_SECRET` | `string` | `""` | Shared HMAC secret for signed media URLs. |
| `CDN_SIGNING_TTL_S` | `int` | `3600` | Expiration time for signed CDN stream URLs in seconds. |

---

## 🔌 External Providers Integration

To populate real metadata, poster art, and stream availability, obtain the following free or developer API keys:

### 1. TMDB (The Movie Database)
1. Sign up for a free account at [themoviedb.org](https://www.themoviedb.org/).
2. Go to **Settings** > **API**.
3. Generate an **API Read Access Token (v4)** or **API Key (v3)**.
4. Add to your `.env`:
   ```ini
   TMDB_READ_TOKEN=eyJhbGciOiJIUzI1Ni...
   ```

### 2. Watchmode (Streaming Provider Availability)
1. Register for an API key at [api.watchmode.com](https://api.watchmode.com/).
2. Add your key to `.env`:
   ```ini
   WATCHMODE_API_KEY=your_watchmode_api_key
   ```

### 3. Internet Archive (Public Domain Streaming)
- Internet Archive does not require an API key.
- By setting `ARCHIVE_ENABLED=true`, admin users can query public domain titles (`/api/v1/admin/archive/search?query=...`) and stream MP4 files directly from Archive.org.

---

## 📡 API Architecture & Endpoints

All application routes are served under the `/api/v1` prefix.

### 🔑 Authentication (`/api/v1/auth`)
| Method | Route | Description |
| :--- | :--- | :--- |
| `POST` | `/register` | Create account (returns 202; sends verification link). |
| `POST` | `/verify-email` | Confirm email with verification token. |
| `POST` | `/resend-verification` | Request a new verification token. |
| `POST` | `/login` | Authenticate; sets `ott_session` cookie & returns CSRF token. |
| `POST` | `/logout` | Revokes the current session and clears cookies. |
| `GET` | `/me` | Returns current user, role, and active profiles list. |
| `POST` | `/forgot-password` | Request password reset token. |
| `POST` | `/reset-password` | Set new password with valid reset token. |

### 👤 Profiles (`/api/v1/profiles`)
| Method | Route | Description |
| :--- | :--- | :--- |
| `GET` | `/` | List all profiles for authenticated user (max 5). |
| `POST` | `/` | Create a new profile (`name`, `avatar`, `is_kid`). |
| `PATCH` | `/{profile_id}` | Update profile name, avatar, or kids setting. |
| `DELETE` | `/{profile_id}` | Delete a profile (cannot delete the last remaining profile). |

### 🍿 Catalog & Titles (`/api/v1/catalog` & `/api/v1/titles`)
| Method | Route | Description |
| :--- | :--- | :--- |
| `GET` | `/catalog` | Filtered titles list (`genre`, `year`, `lang`, `type`, `sort`). |
| `GET` | `/catalog/home` | Curated home feed (featured, trending, continue watching). |
| `GET` | `/catalog/search` | Search titles, cast, crew, and directors. |
| `GET` | `/catalog/genres` | List all available genres. |
| `GET` | `/catalog/languages` | List all available languages. |
| `GET` | `/titles/{title_id}` | Detailed title page (cast, duration, trailer, synopsis). |
| `GET` | `/titles/{title_id}/availability` | Streaming providers for the title in caller's country. |
| `GET` | `/titles/{title_id}/episodes` | List of seasons and episodes for TV series. |

### 📌 Watchlist & Progress (`/api/v1/watchlist` & `/api/v1/progress`)
| Method | Route | Description |
| :--- | :--- | :--- |
| `GET` | `/watchlist` | Get saved titles for active profile (`X-Profile-Id`). |
| `GET` | `/watchlist/ids` | Fast dictionary of saved title IDs. |
| `PUT` | `/watchlist/{title_id}` | Add title to current profile watchlist. |
| `DELETE` | `/watchlist/{title_id}` | Remove title from current profile watchlist. |
| `GET` | `/progress` | Get continue-watching progress list. |
| `PUT` | `/progress` | Save current playback timestamp (`position_s`, `duration_s`). |

### 🎬 Playback (`/api/v1/playback`)
| Method | Route | Description |
| :--- | :--- | :--- |
| `POST` | `/sessions` | Create a playback session for an asset/title (enforces geo-rights). |
| `DELETE` | `/sessions/{session_id}` | Terminate/revoke an active playback session. |

### 🛠️ Admin CMS (`/api/v1/admin`)
| Method | Route | Description |
| :--- | :--- | :--- |
| `GET` / `POST` | `/titles` | List titles with pagination / manually create title. |
| `PATCH` / `DELETE` | `/titles/{title_id}` | Update title details or soft-delete. |
| `POST` | `/titles/import` | Ingest title metadata & poster assets directly from TMDB. |
| `GET` | `/archive/search` | Search public domain videos on Internet Archive. |
| `GET` | `/archive/{identifier}/files` | Inspect streamable video files on Internet Archive item. |
| `GET` / `POST` | `/media-assets` | List / attach video assets (HLS, DASH, MP4, Embeds). |
| `PATCH` / `DELETE` | `/media-assets/{asset_id}` | Update or delete a media stream asset. |
| `GET` / `POST` | `/title-rights` | Manage territory rights (countries, license start/end). |
| `POST` | `/title-rights/{id}/verify` | Validate territory licensing rules. |
| `PATCH` | `/users/{user_id}` | Lock/unlock account, change role, or toggle active status. |
| `GET` | `/audit-logs` | Query chronological administrative audit trail. |

### 🩺 System & Observability
| Method | Route | Description |
| :--- | :--- | :--- |
| `GET` | `/healthz` | Unauthenticated liveness probe (returns `{"status":"ok"}`). |
| `GET` | `/readyz` | Readiness probe (verifies database query, cache ping, provider status). |
| `GET` | `/metrics` | Prometheus metrics scrape endpoint (requires `Authorization: Bearer <METRICS_TOKEN>`). |

---

## 🔒 Authentication & CSRF Security Flow

The API employs a secure authentication model designed for single-page applications (SPA):

```text
[Frontend Client]                                           [FastAPI Backend]
       │                                                            │
       │─── 1. POST /api/v1/auth/login (email, password) ──────────>│
       │                                                            │  (Validates Argon2id hash)
       │<── 2. 200 OK ──────────────────────────────────────────────│  (Sets HttpOnly "ott_session" cookie)
       │       Body: { user: {...}, csrf_token: "xyz..." }          │  (Sets "ott_csrf" cookie)
       │                                                            │
       │─── 3. POST /api/v1/watchlist/123 ─────────────────────────>│
       │       Cookie: ott_session=...; ott_csrf=xyz...             │
       │       Headers: X-CSRF-Token: xyz...                        │
       │                X-Profile-Id: <profile-uuid>                │
       │                                                            │  (Verifies session, double-submit CSRF)
       │<── 4. 200 OK { message: "Saved to watchlist" } ────────────│
```

1. **HttpOnly Cookie**: The session identifier is stored in an `HttpOnly`, `SameSite=Lax` cookie (`ott_session`) preventing script theft.
2. **CSRF Protection**: All mutating calls (`POST`, `PUT`, `PATCH`, `DELETE`) require the `X-CSRF-Token` header matching both the session's internal CSRF secret and the `ott_csrf` cookie.
3. **Active Profile**: State-dependent queries (Watchlist, Continue Watching, Kids filtering) accept an `X-Profile-Id: <UUID>` header.

---

## 🗄 Database Migrations (Alembic)

Database migrations track schema changes across environments.

```bash
# Check current migration revision
alembic current

# Apply all pending migrations to latest
alembic upgrade head

# Create an auto-generated migration after modifying app/models.py
alembic revision --autogenerate -m "Add new column or table"

# Roll back the most recent migration
alembic downgrade -1
```

---

## 🧪 Running Automated Tests

The backend includes a comprehensive suite of unit and integration tests using `pytest`:

```bash
# Run the entire test suite
pytest

# Run tests with verbose output and print logging
pytest -v -s

# Run tests with code coverage report
pytest --cov=app tests/
```

*Note: Tests run against an in-memory SQLite database with mocked upstream HTTP providers, so tests run in seconds without external network dependencies.*

---

## 🛡 Production Deployment & Security Checklist

When deploying this service to a production environment (Kubernetes, AWS ECS, Docker Swarm, VPS):

- [ ] **Set `ENV=production`**: Enables strict security headers (e.g., `Strict-Transport-Security: max-age=63072000; includeSubDomains`).
- [ ] **Set `COOKIE_SECURE=true`**: Enforces the `Secure` flag on all session and CSRF cookies (requires HTTPS).
- [ ] **Restrict `CORS_ORIGINS`**: Explicitly set to your exact domain(s) without trailing slashes (e.g., `https://ott.example.com`).
- [ ] **Enable `TRUST_PROXY=true`**: When deployed behind NGINX, AWS ALB, Cloudflare, or Traefik so client IPs and secure headers are correctly inspected.
- [ ] **Configure `COUNTRY_HEADER`**: Configure your CDN (e.g. `CF-IPCountry` for Cloudflare) to ensure accurate territory rights enforcement.
- [ ] **Configure Outgoing SMTP**: Fill in `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, and `SMTP_PASSWORD` for real email verification and password resets.
- [ ] **Generate Secrets**:
  - `CDN_SIGNING_SECRET`: Use a 64+ character random secret string (`python -c "import secrets; print(secrets.token_hex(32))"`).
  - `METRICS_TOKEN`: Generate a strong random bearer token for Prometheus scraping.
- [ ] **Database Connection Pooling**: Configure `pool_size` and `max_overflow` in `app/db.py` to match your Postgres tier capacity.

---

## 📄 License

This project is licensed under the MIT License.
