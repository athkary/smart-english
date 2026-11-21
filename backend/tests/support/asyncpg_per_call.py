"""CI helper: asyncpg with one short-lived connection per call (event-loop agnostic)."""
from __future__ import annotations

from typing import Any

from app.db.database import IntegrityViolation, UniqueViolation


class AsyncpgPerCallDatabase:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def _run(self, method: str, query: str, args: tuple) -> Any:
        import asyncpg

        conn = await asyncpg.connect(self._dsn)
        try:
            return await getattr(conn, method)(query, *args)
        except asyncpg.UniqueViolationError as exc:
            raise UniqueViolation(str(exc)) from exc
        except asyncpg.IntegrityConstraintViolationError as exc:
            raise IntegrityViolation(str(exc)) from exc
        finally:
            await conn.close()

    async def fetch(self, query: str, *args: Any) -> list[dict]:
        return [dict(r) for r in await self._run("fetch", query, args)]

    async def fetchrow(self, query: str, *args: Any) -> dict | None:
        r = await self._run("fetchrow", query, args)
        return dict(r) if r is not None else None

    async def execute(self, query: str, *args: Any) -> None:
        await self._run("execute", query, args)

    async def close(self) -> None:
        return None
