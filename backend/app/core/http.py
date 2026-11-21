"""HTTP helpers: JSON bodies, bilingual errors, auth guards, rate limiting.

The HTTP layer is plain Starlette (the ASGI toolkit FastAPI is built on), with pydantic
models for validation. Route handlers stay thin; logic lives in module services.
"""
from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict, deque
from datetime import date, datetime
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .security import InvalidTokenError, TokenClaims, decode_access_token

M = TypeVar("M", bound=BaseModel)
MAX_BODY_BYTES = 64 * 1024


class AppError(Exception):
    def __init__(self, code: str, message: str, message_ar: str, status_code: int = 400,
                 headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.message_ar = code, message, message_ar
        self.status_code, self.headers = status_code, headers


# Common errors (bilingual)
def not_found() -> AppError:
    return AppError("not_found", "Not found", "غير موجود", 404)


def unauthorized() -> AppError:
    return AppError("unauthorized", "Sign-in required", "يجب تسجيل الدخول", 401,
                    headers={"WWW-Authenticate": "Bearer"})


def forbidden() -> AppError:
    return AppError("forbidden", "Not allowed", "غير مسموح", 403)


def _default(o: Any) -> Any:
    if isinstance(o, (uuid.UUID,)):
        return str(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, BaseModel):
        return o.model_dump(mode="json")
    raise TypeError(f"not serializable: {type(o).__name__}")


class AppJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False, default=_default, separators=(",", ":")).encode()


def ok(content: Any, status_code: int = 200) -> AppJSONResponse:
    if isinstance(content, BaseModel):
        content = content.model_dump(mode="json")
    return AppJSONResponse(content, status_code=status_code)


def no_content() -> Response:
    return Response(status_code=204)


def error_response(request: Request, exc: AppError) -> AppJSONResponse:
    rid = request.scope.get("state", {}).get("request_id")
    return AppJSONResponse({"error": {"code": exc.code, "message": exc.message,
                                      "message_ar": exc.message_ar, "request_id": rid}},
                           status_code=exc.status_code, headers=exc.headers)


async def read_json(request: Request, model: type[M]) -> M:
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise AppError("payload_too_large", "Request too large", "الطلب كبير جداً", 413)
    try:
        return model.model_validate_json(body or b"{}")
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        raise AppError("validation_error", f"Invalid fields: {', '.join(fields)}",
                       "بعض البيانات غير صحيحة: " + "، ".join(fields), 422) from None


def require_auth(request: Request, *, role: str) -> TokenClaims:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise unauthorized()
    settings = request.app.state.settings
    try:
        claims = decode_access_token(token, secret=settings.jwt_secret.get_secret_value(),
                                     issuer=settings.jwt_issuer)
    except InvalidTokenError:
        raise unauthorized() from None
    if claims.role != role:
        raise forbidden()
    return claims


def path_uuid(request: Request, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(request.path_params[name])
    except (ValueError, KeyError):
        raise not_found() from None


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """In-process sliding-window limiter (single instance). Move to Redis before scaling out."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: float) -> None:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= limit:
            retry = int(window_seconds - (now - q[0])) + 1
            raise AppError("rate_limited", "Too many attempts, try again shortly",
                           "محاولات كثيرة، حاول بعد قليل", 429, headers={"Retry-After": str(retry)})
        q.append(now)
