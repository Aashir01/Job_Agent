"""Routes LLM work across providers, enforces the batch budget, logs cost.

§8: Gemini Flash is primary at ≤300 calls per batch; Groq takes the overflow.
§10: every call is logged with its cost, so quota exhaustion is diagnosable.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from ..config import Settings, get_settings
from ..db import Database, DatabaseError
from .base import LLMError, LLMResponse, QuotaExhausted, Tier
from .gemini import GeminiProvider
from .groq import GroqProvider
from .openrouter import OpenRouterProvider

log = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def parse_json(text: str) -> dict[str, Any]:
    """Parse a model's JSON, tolerating fences and surrounding prose."""
    cleaned = _FENCE_RE.sub("", text or "").strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError(f"no JSON object in model output: {cleaned[:200]!r}")
        parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed


def _schema_hint(schema: dict[str, Any]) -> str:
    """Restate the expected keys for providers that cannot enforce a schema.

    Gemini enforces `responseSchema` server-side; OpenRouter does not accept
    `response_format` at all behind some providers. Without this restatement the
    model invents its own key set and silently drops fields the pipeline needs
    (required_skills, seniority) — which reads as a thin posting, not a bug.
    """
    properties = schema.get("properties") or {}
    keys = schema.get("required") or list(properties)
    lines = []
    for key in keys:
        spec = properties.get(key, {})
        if spec.get("enum"):
            detail = f"{spec.get('type', 'string')}, one of {spec['enum']}"
        elif spec.get("type") == "array":
            detail = f"array of {(spec.get('items') or {}).get('type', 'string')}"
        else:
            detail = spec.get("type", "string")
        lines.append(f'  "{key}": {detail}')
    return (
        "Reply with a single JSON object only — no prose, no code fences — "
        "containing exactly these keys:\n" + "\n".join(lines)
    )


class LLMRouter:
    def __init__(
        self,
        settings: Settings | None = None,
        db: Database | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.settings = settings or get_settings()
        self.db = db
        self._client = client
        self._owns_client = client is None
        self.calls_this_batch = 0
        self.cost_this_batch = 0.0
        self.calls_by_provider: dict[str, int] = {}
        # Set per run from the dashboard's run console; None means use the
        # setting, so an untouched install keeps the configured ceiling.
        self.budget_limit: int | None = None

        s = self.settings
        self.providers = [
            OpenRouterProvider(
                s.openrouter_api_key,
                s.openrouter_cheap_model,
                s.openrouter_good_model,
                fallbacks=s.openrouter_fallbacks,
                disable_reasoning=s.openrouter_disable_reasoning,
            ),
            GeminiProvider(s.gemini_api_key, s.gemini_cheap_model, s.gemini_good_model),
            GroqProvider(s.groq_api_key, s.groq_cheap_model, s.groq_good_model),
        ]

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @property
    def available(self) -> bool:
        return any(p.available for p in self.providers)

    @property
    def budget(self) -> int:
        return self.budget_limit or self.settings.llm_calls_per_batch

    @property
    def budget_remaining(self) -> int:
        return max(0, self.budget - self.calls_this_batch)

    def reset_budget(self, limit: int | None = None) -> None:
        self.calls_this_batch = 0
        self.cost_this_batch = 0.0
        self.calls_by_provider = {}
        self.budget_limit = limit if limit and limit > 0 else None

    # ── the one entry point ───────────────────────────────────────────────
    async def generate(
        self,
        prompt: str,
        *,
        agent: str,
        tier: Tier = "cheap",
        schema: dict[str, Any] | None = None,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        batch_id: str | None = None,
        job_id: str | None = None,
    ) -> LLMResponse:
        if self.calls_this_batch >= self.budget:
            raise QuotaExhausted(
                f"batch budget of {self.budget} LLM calls is spent (agent={agent})"
            )
        if not self.available:
            raise LLMError("no LLM provider is configured", retryable=False)

        # Budget is consumed by the attempt, not by the success: a rate-limited
        # call still costs the provider's quota.
        self.calls_this_batch += 1
        errors: list[str] = []

        for provider in self.providers:
            if not provider.available:
                continue
            try:
                resp = await provider.generate(
                    prompt,
                    tier=tier,
                    schema=schema,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    client=self.client,
                )
            except LLMError as exc:
                # A rate-limited call still spent the provider's quota.
                self.calls_by_provider[provider.name] = (
                    self.calls_by_provider.get(provider.name, 0) + 1
                )
                errors.append(f"{provider.name}: {exc}")
                await self._log(
                    agent, provider.name, provider.models[tier], tier,
                    batch_id, job_id, ok=False, error=str(exc)[:500],
                )
                if not exc.retryable:
                    break
                continue

            self.cost_this_batch += resp.cost_usd
            self.calls_by_provider[resp.provider] = (
                self.calls_by_provider.get(resp.provider, 0) + 1
            )
            await self._log(
                agent, resp.provider, resp.model, tier, batch_id, job_id,
                ok=True, resp=resp,
            )
            return resp

        raise LLMError("all providers failed: " + " | ".join(errors), retryable=False)

    async def generate_json(self, prompt: str, **kw: Any) -> dict[str, Any]:
        """Strict-JSON call. One repair attempt before giving up."""
        schema = kw.get("schema")
        if schema:
            prompt = f"{prompt}\n\n{_schema_hint(schema)}"

        resp = await self.generate(prompt, **kw)
        try:
            return parse_json(resp.text)
        except ValueError as exc:
            log.warning("%s returned unparseable JSON (%s); retrying once", kw.get("agent"), exc)
            repair = (
                f"{prompt}\n\nYour previous reply was not valid JSON. "
                f"Reply with the JSON object only — no prose, no code fences."
            )
            resp = await self.generate(repair, **{**kw, "temperature": 0.0})
            return parse_json(resp.text)

    # ── §10 cost log ──────────────────────────────────────────────────────
    async def _log(
        self,
        agent: str,
        provider: str,
        model: str,
        tier: str,
        batch_id: str | None,
        job_id: str | None,
        *,
        ok: bool,
        resp: LLMResponse | None = None,
        error: str | None = None,
    ) -> None:
        row = {
            "batch_id": batch_id,
            "job_id": job_id,
            "agent": agent,
            "provider": provider,
            "model": model,
            "tier": tier,
            "prompt_tokens": resp.prompt_tokens if resp else 0,
            "completion_tokens": resp.completion_tokens if resp else 0,
            "cost_usd": resp.cost_usd if resp else 0,
            "latency_ms": resp.latency_ms if resp else 0,
            "ok": ok,
            "error": error,
        }
        if self.db is None:
            log.info("llm_call %s", row)
            return
        try:
            await self.db.insert("llm_calls", row, returning=False)
        except DatabaseError as exc:
            # Never let the ledger take down the batch — but never lose the line.
            log.error("failed to write llm_calls row (%s): %s", exc, row)

    async def record_quota(self) -> None:
        """Roll this batch's provider usage into the daily ledger (§8).

        One write per provider per batch, not one per call: the per-call detail
        already lives in llm_calls, and this is the cross-batch view that says
        whether today's free tier is nearly spent.
        """
        if self.db is None:
            return
        for provider, count in self.calls_by_provider.items():
            try:
                await self.db.rpc("bump_quota", {"resource_name": provider, "amount": count})
            except Exception as exc:
                log.warning("could not record quota for %s: %s", provider, exc)
