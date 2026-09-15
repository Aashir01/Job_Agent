"""OpenRouter — OpenAI-compatible chat completions over many models.

Used as the primary provider when configured: a single key reaches the free
Nemotron / Ling / Laguna models, and the fallback list keeps the batch alive
when one free model is rate-limited.
"""
from __future__ import annotations

import time
from typing import Any, Sequence

import httpx

from .base import LLMError, LLMResponse, Tier, price

URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider:
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        cheap_model: str,
        good_model: str,
        timeout: float = 120.0,
        fallbacks: Sequence[str] | None = None,
        disable_reasoning: bool = True,
    ):
        self.api_key = api_key
        self.models = {"cheap": cheap_model, "good": good_model}
        self.fallbacks = [m for m in (fallbacks or []) if m]
        self.timeout = timeout
        self.disable_reasoning = disable_reasoning

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def candidates(self, tier: Tier) -> list[str]:
        """The tier's model first, then the shared fallbacks, deduped in order."""
        ordered = [self.models[tier], *self.fallbacks]
        seen: list[str] = []
        for model in ordered:
            if model and model not in seen:
                seen.append(model)
        return seen

    async def generate(
        self,
        prompt: str,
        *,
        tier: Tier = "cheap",
        schema: dict[str, Any] | None = None,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        client: httpx.AsyncClient | None = None,
    ) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        started = time.perf_counter()
        owns = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout)
        errors: list[str] = []
        try:
            for model in self.candidates(tier):
                body: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                # `response_format: json_object` is deliberately not sent. It is
                # not universally supported behind OpenRouter: nemotron-3-ultra
                # answers it with empty content and ling-3.0-flash-fin rejects
                # the whole request with a 400. JSON is asked for in the prompt
                # instead, and the router parses and repairs once.
                if self.disable_reasoning:
                    # Reasoning models otherwise spend the entire token budget on
                    # hidden thinking and never reach the answer at all.
                    body["reasoning"] = {"enabled": False}

                try:
                    resp = await client.post(
                        URL,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=body,
                        timeout=self.timeout,
                    )
                except httpx.HTTPError as exc:
                    raise LLMError(f"openrouter transport: {exc}") from exc

                if resp.status_code >= 400:
                    errors.append(f"{model} {resp.status_code}: {resp.text[:200]}")
                    continue

                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    errors.append(f"{model} returned no choices")
                    continue

                text = choices[0].get("message", {}).get("content", "") or ""
                usage = data.get("usage", {})
                pt = int(usage.get("prompt_tokens", 0))
                ct = int(usage.get("completion_tokens", 0))
                return LLMResponse(
                    text=text,
                    provider=self.name,
                    model=model,
                    tier=tier,
                    prompt_tokens=pt,
                    completion_tokens=ct,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    cost_usd=float(usage.get("cost") or 0.0) or price(model, pt, ct),
                    raw=data,
                )
        finally:
            if owns:
                await client.aclose()

        raise LLMError(
            "openrouter: all candidate models failed: " + " | ".join(errors),
            retryable=True,
        )
