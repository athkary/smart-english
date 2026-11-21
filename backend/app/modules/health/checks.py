"""Dependency readiness checks (Postgres, Redis).

The Redis check speaks RESP directly over asyncio so it has no client-library dependency.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import unquote, urlparse


@dataclass
class CheckResult:
    name: str
    ok: bool
    latency_ms: float
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "latency_ms": round(self.latency_ms, 1), "detail": self.detail}


Check = Callable[[], Awaitable[None]]


async def run_check(name: str, check: Check, timeout: float = 2.0) -> CheckResult:
    start = time.perf_counter()
    try:
        await asyncio.wait_for(check(), timeout=timeout)
        return CheckResult(name, True, (time.perf_counter() - start) * 1000)
    except asyncio.TimeoutError:
        return CheckResult(name, False, (time.perf_counter() - start) * 1000, "timeout")
    except Exception as exc:  # noqa: BLE001 - report any failure as not-ready
        return CheckResult(name, False, (time.perf_counter() - start) * 1000, type(exc).__name__)


async def run_checks(checks: dict[str, Check], timeout: float = 2.0) -> tuple[bool, dict[str, dict]]:
    results = await asyncio.gather(*(run_check(n, c, timeout) for n, c in checks.items()))
    return all(r.ok for r in results), {r.name: r.as_dict() for r in results}


def _resp_command(*parts: str) -> bytes:
    out = [f"*{len(parts)}\r\n".encode()]
    for p in parts:
        b = p.encode()
        out.append(b"$%d\r\n%s\r\n" % (len(b), b))
    return b"".join(out)


def redis_ping_check(redis_url: str) -> Check:
    url = urlparse(redis_url)
    if url.scheme not in ("redis", "rediss"):
        raise ValueError("redis_url must start with redis:// or rediss://")

    async def check() -> None:
        ssl = url.scheme == "rediss"
        reader, writer = await asyncio.open_connection(url.hostname or "localhost", url.port or 6379, ssl=ssl)
        try:
            if url.password:
                args = ["AUTH", unquote(url.username), unquote(url.password)] if url.username else ["AUTH", unquote(url.password)]
                writer.write(_resp_command(*args))
                await writer.drain()
                line = await reader.readline()
                if not line.startswith(b"+OK"):
                    raise ConnectionError("redis auth failed")
            writer.write(_resp_command("PING"))
            await writer.drain()
            line = await reader.readline()
            if not line.startswith(b"+PONG"):
                raise ConnectionError(f"unexpected redis reply: {line[:40]!r}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    return check
