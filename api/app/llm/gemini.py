"""Gemini Flash — the primary provider (§8: generous RPD, ≤300 calls/batch)."""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .base import LLMError, LLMResponse, Tier, price

BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider:
    name = "gemini"

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
        gen_config: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if schema is not None:
            gen_config["responseMimeType"] = "application/json"
            gen_config["responseSchema"] = schema

        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        started = time.perf_counter()
        owns = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout)
        try:
            resp = await client.post(
                f"{BASE}/{model}:generateContent",
                params={"key": self.api_key},
                json=body,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"gemini transport: {exc}") from exc
        finally:
            if owns:
                await client.aclose()

        if resp.status_code >= 400:
            # 429 = rate limited, 5xx = upstream trouble: both worth a fallback.
            raise LLMError(
                f"gemini {resp.status_code}: {resp.text[:300]}",
                retryable=resp.status_code == 429 or resp.status_code >= 500,
                status=resp.status_code,
            )

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError(f"gemini returned no candidates: {json.dumps(data)[:300]}")
        parts = candidates[0].get("content", {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        usage = data.get("usageMetadata", {})
        pt = int(usage.get("promptTokenCount", 0))
        ct = int(usage.get("candidatesTokenCount", 0))
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
