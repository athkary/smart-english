"""Minimal async database interface.

Queries use PostgreSQL-native `$1, $2 ...` placeholders. All multi-table writes are
written as single statements (data-modifying CTEs), so each write is atomic without
needing client-side transactions.
"""
from __future__ import annotations

from typing import Any, Protocol

Row = dict[str, Any]


class DatabaseError(Exception):
    pass


class UniqueViolation(DatabaseError):
    pass


class IntegrityViolation(DatabaseError):
    """Check / foreign-key / not-null violations."""


class Database(Protocol):
    async def fetch(self, query: str, *args: Any) -> list[Row]: ...
    async def fetchrow(self, query: str, *args: Any) -> Row | None: ...
    async def execute(self, query: str, *args: Any) -> None: ...
    async def close(self) -> None: ...


def clean_dsn(dsn: str) -> str:
    """Hosted Postgres (e.g. Neon) URLs may carry libpq-only options asyncpg doesn't accept."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(dsn)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in {"channel_binding"}]
    scheme = "postgresql" if parts.scheme in ("postgres", "postgresql") else parts.scheme
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class AsyncpgDatabase:
    """Production driver (asyncpg connection pool)."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str, *, min_size: int = 1, max_size: int = 5) -> "AsyncpgDatabase":
        import asyncpg

        pool = await asyncpg.create_pool(clean_dsn(dsn), min_size=min_size, max_size=max_size, command_timeout=10)
        return cls(pool)

    async def _run(self, method: str, query: str, args: tuple) -> Any:
        import asyncpg

        try:
            async with self._pool.acquire() as conn:
                return await getattr(conn, method)(query, *args)
        except asyncpg.UniqueViolationError as exc:
            raise UniqueViolation(str(exc)) from exc
        except asyncpg.IntegrityConstraintViolationError as exc:
            raise IntegrityViolation(str(exc)) from exc

    async def fetch(self, query: str, *args: Any) -> list[Row]:
        return [dict(r) for r in await self._run("fetch", query, args)]

    async def fetchrow(self, query: str, *args: Any) -> Row | None:
        row = await self._run("fetchrow", query, args)
        return dict(row) if row is not None else None

    async def execute(self, query: str, *args: Any) -> None:
        await self._run("execute", query, args)

    async def close(self) -> None:
        await self._pool.close()
