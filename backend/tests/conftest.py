"""Shared fixtures.

Database tests run against a REAL PostgreSQL:
  * TEST_DATABASE_URL set (CI)          -> asyncpg driver against that server
  * else, local Postgres binaries found -> a throwaway cluster + the psql adapter
  * else                                -> DB tests are skipped
"""
from __future__ import annotations

import asyncio
import glob
import os
import shutil
import socket
import subprocess
import tempfile
import time

import pytest

from app.core.config import Settings
from app.db.migrate import migrate

PG_BIN = next(iter(sorted(glob.glob("/usr/lib/postgresql/*/bin"), reverse=True)), None)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="session")
def pg_server():
    """Yields a factory that returns a fresh empty database (Database object) per call."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        pytest.importorskip("asyncpg")
        yield ("asyncpg", url)
        return
    if not PG_BIN or not shutil.which("psql"):
        pytest.skip("No PostgreSQL available")
    tmp = tempfile.mkdtemp(prefix="se-pg-")
    data = os.path.join(tmp, "data")
    as_user: list[str] = []
    if os.geteuid() == 0:  # initdb refuses to run as root
        os.chmod(tmp, 0o777)
        as_user = ["su", "postgres", "-c"]
    port = _free_port()

    def sh(cmd: str) -> None:
        if as_user:
            subprocess.run(as_user + [cmd], check=True, stdout=subprocess.DEVNULL)
        else:
            subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL)

    sh(f"{PG_BIN}/initdb -D {data} -A trust -U postgres >/dev/null")
    sh(f"{PG_BIN}/pg_ctl -D {data} -o '-k {tmp} -p {port} -c fsync=off' -l {tmp}/log -w start >/dev/null")
    yield ("psql", {"host": tmp, "port": port, "user": "postgres"})
    sh(f"{PG_BIN}/pg_ctl -D {data} -m immediate stop >/dev/null")
    shutil.rmtree(tmp, ignore_errors=True)


_counter = 0


@pytest.fixture()
def db(pg_server):
    """A freshly-migrated, isolated database."""
    global _counter
    _counter += 1
    kind, info = pg_server
    name = f"t{os.getpid()}_{_counter}"
    if kind == "psql":
        from tests.support.psql_db import PsqlDatabase

        admin = PsqlDatabase(info["host"], info["port"], info["user"], "postgres")
        run(admin.execute(f"CREATE DATABASE {name}"))
        database = PsqlDatabase(info["host"], info["port"], info["user"], name)
        run(migrate(database))
        yield database
    else:
        from tests.support.asyncpg_per_call import AsyncpgPerCallDatabase

        admin = AsyncpgPerCallDatabase(info)
        run(admin.execute(f"CREATE DATABASE {name}"))
        base, _, _ = info.rpartition("/")
        database = AsyncpgPerCallDatabase(f"{base}/{name}")
        run(migrate(database))
        yield database


@pytest.fixture()
def settings() -> Settings:
    return Settings(environment="test", jwt_secret="t" * 40, scrypt_n=2**12,
                    cors_origins=["http://127.0.0.1:5500"])
