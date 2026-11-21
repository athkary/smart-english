"""SMART ENGLISH AI — ASGI application factory.

Run: uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --proxy-headers
"""
from __future__ import annotations

import contextlib
import logging

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.core.config import Settings, get_settings
from app.core.http import AppError, RateLimiter, error_response
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.database import AsyncpgDatabase, Database
from app.db.migrate import migrate
from app.modules.auth.service import AuthService
from app.modules.health.checks import Check, redis_ping_check
from app.modules.profiles.service import ProfileService
from app.providers.base import ProviderRegistry, ProviderNotConfigured
from app.routes import routes

log = logging.getLogger("smart_english")

_HTTP_AR = {404: "غير موجود", 405: "الطريقة غير مسموحة", 401: "يجب تسجيل الدخول", 403: "غير مسموح"}


async def _http_exc(request: Request, exc: HTTPException):
    return error_response(request, AppError(f"http_{exc.status_code}", str(exc.detail),
                                            _HTTP_AR.get(exc.status_code, "حدث خطأ"), exc.status_code))


async def _app_exc(request: Request, exc: AppError):
    return error_response(request, exc)


async def _provider_exc(request: Request, exc: ProviderNotConfigured):
    return error_response(request, AppError("feature_unavailable", str(exc), "هذه الميزة غير متاحة بعد", 503))


async def _server_exc(request: Request, exc: Exception):
    log.exception("unhandled error")
    return error_response(request, AppError("server_error", "Something went wrong", "حدث خطأ غير متوقع", 500))


def create_app(settings: Settings | None = None, *, db: Database | None = None,
               readiness_checks: dict[str, Check] | None = None) -> Starlette:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        owned = None
        database = db
        if database is None:
            database = owned = await AsyncpgDatabase.connect(settings.database_url)
        if settings.auto_migrate:
            applied = await migrate(database)
            if applied:
                log.info("migrations applied", extra={"fields": {"versions": applied}})
        _wire(app, settings, database, readiness_checks)
        log.info("app started", extra={"fields": {"env": settings.environment.value,
                                                  "version": settings.server_version}})
        try:
            yield
        finally:
            if owned is not None:
                await owned.close()

    middleware = [Middleware(RequestContextMiddleware)]
    if settings.cors_origins:
        middleware.insert(0, Middleware(
            CORSMiddleware, allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Accept-Language"],
            expose_headers=["X-Request-ID", "Retry-After"], max_age=600))

    app = Starlette(routes=routes, middleware=middleware, lifespan=lifespan,
                    exception_handlers={HTTPException: _http_exc, AppError: _app_exc,
                                        ProviderNotConfigured: _provider_exc, Exception: _server_exc})
    app.state.settings = settings
    return app


def _wire(app: Starlette, settings: Settings, db: Database, checks: dict[str, Check] | None) -> None:
    async def db_check() -> None:
        row = await db.fetchrow("SELECT 1 AS ok")
        if not row or row["ok"] != 1:
            raise ConnectionError("db")

    if checks is None:
        checks = {"postgres": db_check}
        if settings.redis_url:
            checks["redis"] = redis_ping_check(settings.redis_url)
    app.state.db = db
    app.state.readiness_checks = checks
    app.state.providers = ProviderRegistry()
    app.state.rate_limiter = RateLimiter()
    app.state.auth_service = AuthService(db, settings)
    app.state.profile_service = ProfileService(db, settings)
