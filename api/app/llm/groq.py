"""Groq — overflow only (§8). OpenAI-compatible chat completions."""
from __future__ import annotations

import time
from typing import Any

import httpx

from .base import LLMError, LLMResponse, Tier, price

URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider:
    name = "groq"

    def __init__(self, api_key: str, cheap_model: str, good_model: str, timeout: float = 30.0):
        self.api_key = api_key
        self.models = {"cheap": cheap_model, "good": good_model}
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

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
        model = self.models[tier]
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            body["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        owns = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout)
        try:
            resp = await client.post(
                URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"groq transport: {exc}") from exc
        finally:
            if owns:
                await client.aclose()

        if resp.status_code >= 400:
            raise LLMError(
                f"groq {resp.status_code}: {resp.text[:300]}",
                retryable=resp.status_code == 429 or resp.status_code >= 500,
                status=resp.status_code,
            )

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("groq returned no choices")
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
            cost_usd=price(model, pt, ct),
            raw=data,
        )
