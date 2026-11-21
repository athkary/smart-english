"""Tiny ordered SQL migration runner.

Files: migrations/sql/NNNN_name.sql (no BEGIN/COMMIT inside — the runner wraps each
file and its bookkeeping row in one transaction). Run: `python -m app.db.migrate`.
Designed for a single app instance (Render free tier); add an advisory lock before scaling out.
"""
from __future__ import annotations

import asyncio
import logging
import pathlib
import re

from .database import Database

log = logging.getLogger("smart_english.migrate")
MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "sql"
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def discover(directory: pathlib.Path = MIGRATIONS_DIR) -> list[tuple[str, pathlib.Path]]:
    found = sorted((m.group(1), p) for p in directory.iterdir() if (m := _NAME.match(p.name)))
    versions = [v for v, _ in found]
    if len(versions) != len(set(versions)):
        raise RuntimeError("duplicate migration version")
    return found


async def migrate(db: Database, directory: pathlib.Path = MIGRATIONS_DIR) -> list[str]:
    await db.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                     "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
    applied = {r["version"] for r in await db.fetch("SELECT version FROM schema_migrations")}
    done: list[str] = []
    for version, path in discover(directory):
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        if re.search(r"^\s*(BEGIN|COMMIT)\s*;", sql, re.I | re.M):
            raise RuntimeError(f"{path.name}: remove BEGIN/COMMIT, the runner adds them")
        await db.execute(f"BEGIN;\n{sql}\n;INSERT INTO schema_migrations(version) VALUES ('{version}');\nCOMMIT;")
        log.info("migration applied", extra={"fields": {"version": version}})
        done.append(version)
    return done


async def _main() -> None:
    from app.core.config import get_settings
    from .database import AsyncpgDatabase

    db = await AsyncpgDatabase.connect(get_settings().database_url)
    try:
        print("applied:", await migrate(db) or "nothing (up to date)")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(_main())
