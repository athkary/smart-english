"""Minimal synchronous ASGI test client (no httpx needed). Runs the app's real lifespan."""
from __future__ import annotations

import asyncio
import json as jsonlib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Resp:
    status_code: int
    headers: dict[str, str]
    body: bytes = b""
    _json: Any = field(default=None, repr=False)

    def json(self) -> Any:
        return jsonlib.loads(self.body)


class Client:
    def __init__(self, app, *, client_ip: str = "10.0.0.1") -> None:
        self.app, self.ip = app, client_ip
        self.runner = asyncio.Runner()
        self._lifespan_in: asyncio.Queue | None = None
        self._lifespan_task = None

    def __enter__(self) -> "Client":
        self.runner.run(self._startup())
        return self

    def __exit__(self, *exc) -> None:
        self.runner.run(self._shutdown())
        self.runner.close()

    async def _startup(self) -> None:
        self._lifespan_in = asyncio.Queue()
        out: asyncio.Queue = asyncio.Queue()
        await self._lifespan_in.put({"type": "lifespan.startup"})

        async def send(msg):
            await out.put(msg)

        self._lifespan_task = asyncio.ensure_future(
            self.app({"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}, self._lifespan_in.get, send))
        msg = await out.get()
        if msg["type"] != "lifespan.startup.complete":
            raise RuntimeError(f"startup failed: {msg}")
        self._out = out

    async def _shutdown(self) -> None:
        await self._lifespan_in.put({"type": "lifespan.shutdown"})
        await self._out.get()
        await self._lifespan_task

    def request(self, method: str, path: str, *, json: Any = None, token: str | None = None,
                headers: dict[str, str] | None = None) -> Resp:
        return self.runner.run(self._request(method, path, json, token, headers or {}))

    async def _request(self, method, path, json, token, headers) -> Resp:
        body = b"" if json is None else jsonlib.dumps(json).encode()
        hdrs = {"host": "testserver", **{k.lower(): v for k, v in headers.items()}}
        if json is not None:
            hdrs["content-type"] = "application/json"
        if token:
            hdrs["authorization"] = f"Bearer {token}"
        path_only, _, query = path.partition("?")
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
                 "scheme": "http", "path": path_only, "raw_path": path_only.encode(), "query_string": query.encode(),
                 "headers": [(k.encode(), v.encode()) for k, v in hdrs.items()],
                 "client": (self.ip, 1234), "server": ("testserver", 80), "root_path": "", "state": {}}
        sent = False
        status, resp_headers, chunks = 0, {}, []

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.sleep(3600)

        async def send(msg):
            nonlocal status, resp_headers
            if msg["type"] == "http.response.start":
                status = msg["status"]
                resp_headers = {k.decode().lower(): v.decode() for k, v in msg.get("headers", [])}
            elif msg["type"] == "http.response.body":
                chunks.append(msg.get("body", b""))

        await self.app(scope, receive, send)
        return Resp(status, resp_headers, b"".join(chunks))

    def get(self, path, **kw): return self.request("GET", path, **kw)
    def post(self, path, **kw): return self.request("POST", path, **kw)
    def patch(self, path, **kw): return self.request("PATCH", path, **kw)
    def put(self, path, **kw): return self.request("PUT", path, **kw)
    def delete(self, path, **kw): return self.request("DELETE", path, **kw)
