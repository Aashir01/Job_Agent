"""Provider-agnostic LLM types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Tier = Literal["cheap", "good"]


class LLMError(RuntimeError):
    """A provider failed in a way worth trying the next provider for."""

    def __init__(self, message: str, *, retryable: bool = True, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class QuotaExhausted(RuntimeError):
    """The per-batch call budget (§8) is spent. Never silently overspend."""


@dataclass(slots=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    tier: Tier
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


# USD per 1M tokens. Free tiers bill nothing, but the spec wants the number
# logged so that exhaustion is diagnosable and a future paid tier is priced.
PRICES: dict[str, tuple[float, float]] = {
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.0-flash-lite": (0.075, 0.30),
    "gemini-1.5-flash": (0.075, 0.30),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.3-70b-versatile": (0.59, 0.79),
}


def price(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    p_in, p_out = PRICES.get(model, (0.0, 0.0))
    return round((prompt_tokens * p_in + completion_tokens * p_out) / 1_000_000, 6)
