"""Test-only Database adapter that runs REAL SQL on a REAL PostgreSQL via the `psql` CLI.

Used where the asyncpg driver is not installed. Parameters are rendered as safely-quoted
literals; column types come from psql's \\gdesc so results are typed like asyncpg's.
Production uses app.db.database.AsyncpgDatabase.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import uuid
from datetime import date, datetime
from typing import Any

from app.db.database import IntegrityViolation, UniqueViolation

_NULL = "\x01NULL\x01"
_SPLIT = "\x02SPLIT\x02"
_PARAM = re.compile(r"\$(\d+)")


def literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (datetime, date)):
        value = value.isoformat()
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = str(value) if not isinstance(value, uuid.UUID) else str(value)
    if "\x00" in text:
        raise ValueError("NUL byte in parameter")
    return "'" + text.replace("'", "''") + "'"


def render(query: str, args: tuple) -> str:
    def sub(m: re.Match) -> str:
        i = int(m.group(1))
        if i < 1 or i > len(args):
            raise IndexError(f"missing parameter ${i}")
        return literal(args[i - 1])

    return _PARAM.sub(sub, query)


def _convert(value: str, pg_type: str) -> Any:
    if value == _NULL:
        return None
    t = pg_type.lower()
    if t == "boolean":
        return value == "t"
    if t in ("smallint", "integer", "bigint"):
        return int(value)
    if t in ("real", "double precision", "numeric"):
        return float(value)
    if t in ("json", "jsonb"):
        return json.loads(value)
    if t == "uuid":
        return uuid.UUID(value)
    if t.startswith("timestamp"):
        return datetime.fromisoformat(value)
    return value


class PsqlDatabase:
    def __init__(self, host: str, port: int, user: str, dbname: str) -> None:
        self._base = ["psql", "-h", host, "-p", str(port), "-U", user, "-d", dbname, "-X", "-q",
                      "-v", "ON_ERROR_STOP=1"]

    async def _psql(self, script: str) -> str:
        proc = await asyncio.create_subprocess_exec(*self._base, stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate(script.encode())
        if proc.returncode != 0:
            msg = err.decode(errors="replace")
            if "duplicate key value violates unique constraint" in msg:
                raise UniqueViolation(msg)
            if re.search(r"violates (check|foreign key|not-null) constraint", msg):
                raise IntegrityViolation(msg)
            raise RuntimeError(msg)
        return out.decode()

    async def fetch(self, query: str, *args: Any) -> list[dict]:
        sql = render(query, args).strip().rstrip(";")
        script = ("\\pset format csv\n\\pset null '" + _NULL + "'\n"
                  f"{sql} \\gdesc\n\\echo {_SPLIT}\n{sql};\n")
        out = await self._psql(script)
        desc_part, _, data_part = out.partition(_SPLIT + "\n")
        desc = list(csv.reader(io.StringIO(desc_part)))
        if not desc or desc[0][:2] != ["Column", "Type"]:
            return []  # statement returns no columns
        types = [row[1] for row in desc[1:]]
        rows = list(csv.reader(io.StringIO(data_part)))
        if not rows:
            return []
        header, body = rows[0], rows[1:]
        return [{h: _convert(v, t) for h, v, t in zip(header, r, types)} for r in body]

    async def fetchrow(self, query: str, *args: Any) -> dict | None:
        rows = await self.fetch(query, *args)
        return rows[0] if rows else None

    async def execute(self, query: str, *args: Any) -> None:
        await self._psql(render(query, args) + "\n")

    async def close(self) -> None:
        return None
