"""Thin async PostgREST client.

Supabase's own SDK is synchronous and pulls in more than a 256MB machine wants
to carry. PostgREST is a plain REST API; this wraps the five calls we make.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Sequence

import httpx

from .config import Settings, get_settings

log = logging.getLogger(__name__)


class DatabaseError(RuntimeError):
    pass


class NotConfigured(DatabaseError):
    """Raised when Supabase credentials are absent — never silently no-op."""


def _encode(value: Any) -> str:
    if value is None:
        return "is.null"
    if isinstance(value, bool):
        return f"eq.{str(value).lower()}"
    return f"eq.{value}"


class Database:
    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    # ── plumbing ──────────────────────────────────────────────────────────
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            if not self.settings.configured:
                raise NotConfigured(
                    "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set to reach the database"
                )
            key = self.settings.supabase_service_key
            self._client = httpx.AsyncClient(
                base_url=self.settings.supabase_url.rstrip("/") + "/rest/v1",
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                timeout=self.settings.http_timeout_s,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, path: str, **kw: Any) -> Any:
        resp = await self.client.request(method, path, **kw)
        if resp.status_code >= 400:
            raise DatabaseError(f"{method} {path} -> {resp.status_code}: {resp.text[:500]}")
        if resp.status_code == 204 or not resp.content:
            return []
        return resp.json()

    # ── operations ────────────────────────────────────────────────────────
    async def select(
        self,
        table: str,
        *,
        columns: str = "*",
        eq: dict[str, Any] | None = None,
        in_: dict[str, Sequence[Any]] | None = None,
        gte: dict[str, Any] | None = None,
        lte: dict[str, Any] | None = None,
        not_null: Sequence[str] | None = None,
        is_null: Sequence[str] | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict]:
        params: dict[str, Any] = {"select": columns}
        for col, val in (eq or {}).items():
            params[col] = _encode(val)
        for col, vals in (in_ or {}).items():
            joined = ",".join(f'"{v}"' for v in vals)
            params[col] = f"in.({joined})"
        for col, val in (gte or {}).items():
            params[col] = f"gte.{val}"
        for col, val in (lte or {}).items():
            params[col] = f"lte.{val}"
        for col in not_null or ():
            params[col] = "not.is.null"
        for col in is_null or ():
            params[col] = "is.null"
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return await self._request("GET", f"/{table}", params=params)

    async def select_one(self, table: str, **kw: Any) -> dict | None:
        kw.setdefault("limit", 1)
        rows = await self.select(table, **kw)
        return rows[0] if rows else None

    async def insert(
        self,
        table: str,
        rows: dict | Iterable[dict],
        *,
        upsert: bool = False,
        on_conflict: str | None = None,
        ignore_duplicates: bool = False,
        returning: bool = True,
    ) -> list[dict]:
        payload = [rows] if isinstance(rows, dict) else list(rows)
        if not payload:
            return []
        prefer = ["return=representation" if returning else "return=minimal"]
        if upsert:
            prefer.append(
                "resolution=ignore-duplicates" if ignore_duplicates else "resolution=merge-duplicates"
            )
        params = {"on_conflict": on_conflict} if on_conflict else None
        return await self._request(
            "POST",
            f"/{table}",
            json=payload,
            params=params,
            headers={"Prefer": ",".join(prefer)},
        )

    async def update(
        self, table: str, patch: dict, *, eq: dict[str, Any], returning: bool = True
    ) -> list[dict]:
        if not eq:
            raise DatabaseError("refusing an unfiltered UPDATE")
        params = {col: _encode(val) for col, val in eq.items()}
        return await self._request(
            "PATCH",
            f"/{table}",
            json=patch,
            params=params,
            headers={"Prefer": "return=representation" if returning else "return=minimal"},
        )

    async def delete(self, table: str, *, eq: dict[str, Any]) -> list[dict]:
        if not eq:
            raise DatabaseError("refusing an unfiltered DELETE")
        params = {col: _encode(val) for col, val in eq.items()}
        return await self._request("DELETE", f"/{table}", params=params)

    async def rpc(self, fn: str, params: dict | None = None) -> Any:
        resp = await self.client.post(f"/rpc/{fn}", json=params or {})
        if resp.status_code >= 400:
            raise DatabaseError(f"rpc {fn} -> {resp.status_code}: {resp.text[:500]}")
        return resp.json() if resp.content else None


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db
