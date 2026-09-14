from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.scout.base import normalise_name  # noqa: E402
from app.config import Settings  # noqa: E402

# companies.name_normalised is a stored generated column with a unique index
# (0003). The fake has to model both, or tests pass here and duplicate rows
# appear in production.
GENERATED = {"companies": {"name_normalised": lambda row: normalise_name(row.get("name"))}}
UNIQUE = {"companies": ("name_normalised",), "jobs": ("source_url",)}


class FakeDB:
    """In-memory stand-in for PostgREST. Records writes so tests can assert on them."""

    def __init__(self, tables: dict[str, list[dict]] | None = None, rpc: dict[str, Any] | None = None):
        self.tables: dict[str, list[dict]] = tables or {}
        self.rpc_returns: dict[str, Any] = rpc or {}
        self.rpc_calls: list[tuple[str, dict]] = []
        self.writes: list[tuple[str, str, Any]] = []
        self._id = 0

    def _match(self, row: dict, eq: dict | None) -> bool:
        return all(row.get(k) == v for k, v in (eq or {}).items())

    async def select(self, table, *, columns="*", eq=None, in_=None, gte=None, lte=None,
                     not_null=None, is_null=None, order=None, limit=None, offset=None):
        rows = [r for r in self.tables.get(table, []) if self._match(r, eq)]
        for col, values in (in_ or {}).items():
            rows = [r for r in rows if r.get(col) in set(values)]
        for col, value in (lte or {}).items():
            rows = [r for r in rows if r.get(col) is not None and r[col] <= value]
        for col, value in (gte or {}).items():
            rows = [r for r in rows if r.get(col) is not None and r[col] >= value]
        for col in not_null or ():
            rows = [r for r in rows if r.get(col) is not None]
        for col in is_null or ():
            rows = [r for r in rows if r.get(col) is None]
        return rows[: limit or len(rows)]

    async def select_one(self, table, **kw):
        rows = await self.select(table, **{**kw, "limit": 1})
        return rows[0] if rows else None

    async def insert(self, table, rows, *, upsert=False, on_conflict=None,
                     ignore_duplicates=False, returning=True):
        payload = [rows] if isinstance(rows, dict) else list(rows)
        stored = []
        for row in payload:
            record = {**row}
            for column, compute in GENERATED.get(table, {}).items():
                record[column] = compute(record)

            existing = None
            for column in UNIQUE.get(table, ()):
                if record.get(column) in (None, ""):
                    continue
                existing = next(
                    (r for r in self.tables.get(table, []) if r.get(column) == record[column]),
                    None,
                )
                if existing:
                    break

            if existing is not None:
                if not upsert or ignore_duplicates:
                    continue          # PostgREST returns nothing for the skipped row
                existing.update(record)
                stored.append(existing)
                continue

            self._id += 1
            record = {"id": row.get("id") or f"id-{self._id}", **record}
            self.tables.setdefault(table, []).append(record)
            stored.append(record)
        self.writes.append(("insert", table, payload))
        return stored if returning else []

    async def update(self, table, patch, *, eq, returning=True):
        hit = []
        for row in self.tables.get(table, []):
            if self._match(row, eq):
                row.update(patch)
                hit.append(row)
        self.writes.append(("update", table, {"patch": patch, "eq": eq}))
        return hit if returning else []

    async def delete(self, table, *, eq):
        keep = [r for r in self.tables.get(table, []) if not self._match(r, eq)]
        removed = len(self.tables.get(table, [])) - len(keep)
        self.tables[table] = keep
        self.writes.append(("delete", table, eq))
        return [{}] * removed

    async def rpc(self, fn, params=None):
        self.rpc_calls.append((fn, params or {}))
        value = self.rpc_returns.get(fn)
        return value(params or {}) if callable(value) else value

    async def aclose(self):
        pass


@pytest.fixture
def settings() -> Settings:
    return Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_key="service-key",
        agent_key="test-agent-key",
        gemini_api_key="",
        groq_api_key="",
    )


@pytest.fixture
def db() -> FakeDB:
    return FakeDB()


@pytest.fixture
def profile() -> dict:
    return {
        "id": "p1",
        "full_name": "Test Candidate",
        "headline": "AI Engineer",
        "location": "Lahore, Pakistan",
        "work_auth": {"passport": "Pakistan", "needs_sponsorship": True},
        "links": {"github": "github.com/test"},
        "seniority": "senior",
        "salary_floor_usd": 60000,
    }
