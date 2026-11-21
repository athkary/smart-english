import asyncio
import os
import shutil
import socket
import subprocess
import time

import pytest

from app.core.middleware import RequestContextMiddleware
from app.modules.health.checks import redis_ping_check, run_checks


# ---------- middleware (raw ASGI, no framework needed) ----------
async def _call(mw, headers=None):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "method": "GET", "path": "/", "headers": headers or []}
    await mw(scope, receive, send)
    return dict(sent[0]["headers"]), scope


async def _app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"ok"})


def test_request_id_generated_and_security_headers():
    headers, scope = asyncio.run(_call(RequestContextMiddleware(_app)))
    assert len(headers[b"x-request-id"]) == 32
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"x-frame-options"] == b"DENY"
    assert scope["state"]["request_id"] == headers[b"x-request-id"].decode()


def test_valid_incoming_request_id_propagated_invalid_replaced():
    headers, _ = asyncio.run(_call(RequestContextMiddleware(_app), [(b"x-request-id", b"abc-12345678")]))
    assert headers[b"x-request-id"] == b"abc-12345678"
    headers, _ = asyncio.run(_call(RequestContextMiddleware(_app), [(b"x-request-id", b"<script>")]))
    assert headers[b"x-request-id"] != b"<script>"


# ---------- readiness checks ----------
def test_run_checks_reports_failures_and_timeouts():
    async def ok():
        return None

    async def boom():
        raise ConnectionError("down")

    async def slow():
        await asyncio.sleep(5)

    ready, details = asyncio.run(run_checks({"a": ok, "b": boom, "c": slow}, timeout=0.2))
    assert ready is False
    assert details["a"]["ok"] and not details["b"]["ok"] and details["c"]["detail"] == "timeout"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def real_redis():
    exe = shutil.which("redis-server")
    if not exe:
        pytest.skip("redis-server not installed")
    port = _free_port()
    proc = subprocess.Popen([exe, "--port", str(port), "--save", "", "--appendonly", "no",
                             "--requirepass", "s3cret"], stdout=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), 0.1).close()
            break
        except OSError:
            time.sleep(0.05)
    yield port
    proc.terminate()
    proc.wait()


def test_redis_check_against_real_server(real_redis):
    good = redis_ping_check(f"redis://:s3cret@127.0.0.1:{real_redis}/0")
    bad_pw = redis_ping_check(f"redis://:wrong@127.0.0.1:{real_redis}/0")
    ready, details = asyncio.run(run_checks({"good": good, "badpw": bad_pw}))
    assert details["good"]["ok"] is True
    assert details["badpw"]["ok"] is False


def test_redis_check_unreachable():
    ready, details = asyncio.run(run_checks({"r": redis_ping_check(f"redis://127.0.0.1:{_free_port()}/0")}))
    assert not ready and details["r"]["detail"] in {"ConnectionRefusedError", "OSError", "timeout"}
