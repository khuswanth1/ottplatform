import logging
import re
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import metrics
from .cache import cache
from .config import get_settings, production_problems
from .db import get_db
from .deps import SAFE_METHODS
from .providers.base import ProviderError
from .providers.registry import get_registry
from .routers import account, admin, auth, billing, catalog, playback, notifications, profiles, progress, ratings, reminders, reports, titles, watchlist

log = logging.getLogger("ott")
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx logs full URLs; provider keys may be in query strings


_RID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_PERSONAL = ("/api/v1/catalog/recommended",)  # per-profile answers: never cacheable by anyone else


def _cache_policy(request: Request) -> str:
    """Catalog and title responses depend on the viewer (profile maturity, plan, country), so a shared cache must never
    hold them: anything carrying a session cookie or a profile header is `private`; only anonymous answers are public."""
    p = request.url.path
    if p.startswith(_PERSONAL):
        return "no-store"
    if p.startswith(("/api/v1/catalog/genres", "/api/v1/catalog/languages")):
        age = "max-age=86400, stale-while-revalidate=86400"
    elif p.startswith("/api/v1/catalog"):
        age = "max-age=120, stale-while-revalidate=600"
    elif p.startswith("/api/v1/titles"):
        age = "max-age=300, stale-while-revalidate=600"
    else:
        return "no-store"
    personal = bool(request.cookies.get("ott_session") or request.headers.get("x-profile-id"))
    return f"{'private' if personal else 'public'}, {age}"


class BodyLimit:
    """Rejects oversized request bodies (Content-Length and streamed)."""

    def __init__(self, app, max_bytes: int):
        self.app, self.max = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        for k, v in scope["headers"]:
            if k == b"content-length" and v.isdigit() and int(v) > self.max:
                return await JSONResponse({"detail": "Request body too large."}, status_code=413)(scope, receive, send)
        seen = 0

        async def limited():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max:
                    raise HTTPException(413, "Request body too large.")
            return msg

        await self.app(scope, limited, send)


def create_app() -> FastAPI:
    s = get_settings()
    if s.is_prod:
        fatal, warn = production_problems(s)
        for w in warn:
            log.warning("production config: %s", w)
        if fatal:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(fatal))
    app = FastAPI(
        title="OTT Platform API", version="1.0.0",
        docs_url="/api/v1/docs" if s.enable_docs else None,
        redoc_url=None, openapi_url="/api/v1/openapi.json" if s.enable_docs else None,
    )
    app.state.enforce_limits = False

    app.add_middleware(BodyLimit, max_bytes=s.max_body_bytes)
    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Profile-Id"], max_age=600,
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        supplied = request.headers.get("x-request-id", "")
        rid = supplied if _RID.match(supplied) else uuid.uuid4().hex[:16]  # never echo arbitrary client text into logs/headers
        # Origin check: browsers always send Origin on cross-site unsafe requests (defence in depth with CSRF tokens)
        origin = request.headers.get("origin")
        if request.method not in SAFE_METHODS and origin and origin not in s.cors_origins:
            return JSONResponse({"detail": "Cross-origin request blocked."}, status_code=403)
        t0 = time.perf_counter()
        try:
            resp = await call_next(request)
        except Exception:
            log.exception("unhandled error rid=%s path=%s", rid, request.url.path)
            resp = JSONResponse({"detail": "Internal server error.", "request_id": rid}, status_code=500)
        ms = (time.perf_counter() - t0) * 1000
        route = request.scope.get("route")
        metrics.inc("http_requests_total", method=request.method, status=str(resp.status_code),
                    route=getattr(route, "path", "unmatched"))
        log.info("%s %s %s %.0fms rid=%s", request.method, request.url.path, resp.status_code, ms, rid)
        resp.headers["X-Request-ID"] = rid
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["X-Frame-Options"] = "DENY"
        if "Cache-Control" not in resp.headers:
            resp.headers["Cache-Control"] = _cache_policy(request) if request.method == "GET" and resp.status_code == 200 else "no-store"
        resp.headers.append("Vary", "Cookie, X-Profile-Id" + (f", {s.country_header}" if s.country_header else ""))
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if s.is_prod:
            resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return resp

    @app.exception_handler(ProviderError)
    async def provider_error(_: Request, exc: ProviderError):
        return JSONResponse({"detail": {"code": "provider_unavailable", "message": str(exc)}}, status_code=502)

    p = "/api/v1"
    for r in (auth, account, billing, profiles, catalog, titles, watchlist, ratings, reminders, notifications, progress, playback, reports, admin):
        app.include_router(r.router, prefix=p)

    @app.get("/", include_in_schema=False)
    def root():
        if s.enable_docs:
            return RedirectResponse(url="/api/v1/docs")
        return {"name": "OTT Platform API", "version": "1.0.0", "status": "online"}

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

    @app.get("/healthz", include_in_schema=False)
    @app.get("/health", include_in_schema=False)
    @app.get("/api/v1/health", include_in_schema=False)
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz(db: Session = Depends(get_db)):
        try:
            db.execute(text("select 1"))
        except Exception:
            raise HTTPException(503, "database unavailable")
        redis_ok = cache.ping()
        # Redis down is degraded, not unready: the API keeps serving (per-worker limits, direct provider calls) and the
        # flag lets monitoring alert on it without a cache outage taking the whole site out of the load balancer.
        return {"status": "ready" if redis_ok else "degraded", "cache": redis_ok, "providers": get_registry().status()}

    @app.get("/metrics", include_in_schema=False)
    def prom(request: Request):
        tok = s.metrics_token
        if not tok or request.headers.get("authorization") != f"Bearer {tok}":
            raise HTTPException(404)
        return PlainTextResponse(metrics.render())

    return app


app = create_app()
