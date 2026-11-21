"""Pure ASGI middleware (framework-agnostic, works with FastAPI/Starlette)."""
from __future__ import annotations

import re
import uuid
from typing import Any, Awaitable, Callable

from .logging import request_id_var

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_VALID_RID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")

SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"strict-transport-security", b"max-age=63072000; includeSubDomains"),
    (b"cache-control", b"no-store"),
]


class RequestContextMiddleware:
    """Assigns/propagates X-Request-ID and adds security headers to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode(errors="ignore")
        rid = incoming if _VALID_RID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        scope.setdefault("state", {})["request_id"] = rid

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [h for h in message.get("headers", []) if h[0].lower() != b"x-request-id"]
                existing = {h[0].lower() for h in headers}
                headers.append((b"x-request-id", rid.encode()))
                headers.extend(h for h in SECURITY_HEADERS if h[0] not in existing)
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_var.reset(token)
