"""Start a full local stack for browser tests: throwaway PostgreSQL + API (:8000) + web (:5500).

Usage: python -m tests.e2e.run_stack   (from backend/; Ctrl+C to stop)
Uses the psql test adapter when asyncpg isn't installed.
"""
from __future__ import annotations

import functools
import http.server
import os
import pathlib
import shutil
import subprocess
import tempfile
import threading

import uvicorn

from app.core.config import Settings
from app.main import create_app
from tests.conftest import PG_BIN, _free_port

WEB_DIR = pathlib.Path(__file__).resolve().parents[3] / "web"


def start_postgres():
    tmp = tempfile.mkdtemp(prefix="se-e2e-")
    os.chmod(tmp, 0o777)
    port = _free_port()
    pre = ["su", "postgres", "-c"] if os.geteuid() == 0 else ["sh", "-c"]
    subprocess.run(pre + [f"{PG_BIN}/initdb -D {tmp}/data -A trust -U postgres >/dev/null"], check=True)
    subprocess.run(pre + [f"{PG_BIN}/pg_ctl -D {tmp}/data -o '-k {tmp} -p {port}' -l {tmp}/log -w start >/dev/null"],
                   check=True)
    subprocess.run(["psql", "-h", tmp, "-p", str(port), "-U", "postgres", "-qc", "CREATE DATABASE smart"], check=True)

    def stop():
        subprocess.run(pre + [f"{PG_BIN}/pg_ctl -D {tmp}/data -m fast stop >/dev/null"])
        shutil.rmtree(tmp, ignore_errors=True)

    return tmp, port, stop


def serve_web(port: int = 5500):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(WEB_DIR))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    host, port, stop = start_postgres()
    try:
        from tests.support.psql_db import PsqlDatabase

        db = PsqlDatabase(host, port, "postgres", "smart")
        settings = Settings(environment="local", jwt_secret="e2e" * 16, scrypt_n=2**14,
                            cors_origins=["http://127.0.0.1:5500"])
        serve_web()
        print("web: http://127.0.0.1:5500  api: http://127.0.0.1:8000", flush=True)
        uvicorn.run(create_app(settings, db=db), host="127.0.0.1", port=8000, log_level="warning")
    finally:
        stop()


if __name__ == "__main__":
    main()
