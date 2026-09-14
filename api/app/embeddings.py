"""384-dimension embeddings.

Two providers, both free:

* ``hashing`` (default) — the signed hashing trick over word unigrams, bigrams
  and character 4-grams, sublinear-TF weighted and L2-normalised. Deterministic,
  no model weights, no network, and it runs inside a 256MB Fly machine. Good
  enough for what the spec actually asks embeddings to do: near-duplicate
  detection at cosine > 0.92 and top-N bullet retrieval.
* ``gemini`` — text-embedding-004 with ``outputDimensionality=384``, for when
  retrieval quality matters more than the quota.

Both emit unit vectors, so cosine similarity is a dot product and the two are
interchangeable at the call site — but vectors from different providers are not
comparable, so changing the provider means re-embedding.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable, Sequence

import httpx

from .config import Settings, get_settings

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-]*")
_STOP = frozenset(
    """a an and are as at be by for from has have in is it its of on or that the
    to was were will with you your we our their this these those they he she""".split()
)


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if w not in _STOP and len(w) > 1]


# Relative pull of each feature family. Word identity dominates; character
# n-grams are there for morphology and typos, not for carrying the signal.
W_UNIGRAM, W_BIGRAM, W_CHARGRAM = 1.0, 0.6, 0.3
CHAR_N = 4


def _features(text: str) -> list[tuple[str, float]]:
    """Feature/weight pairs.

    Character n-grams are taken **per word**, never across a joined string:
    striding over the whole text makes every downstream n-gram shift when a
    single word is inserted, which collapses the similarity of two postings
    that differ only by a "(Remote)" in the title.
    """
    words = _tokens(text)
    feats: list[tuple[str, float]] = [(w, W_UNIGRAM) for w in words]
    feats += [(f"{a}_{b}", W_BIGRAM) for a, b in zip(words, words[1:])]
    for word in words:
        if len(word) > CHAR_N:
            padded = f"^{word}$"
            feats += [
                (f"#{padded[i : i + CHAR_N]}", W_CHARGRAM)
                for i in range(len(padded) - CHAR_N + 1)
            ]
    return feats


def _bucket(feature: str, dim: int) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    raw = int.from_bytes(digest, "big")
    return raw % dim, 1.0 if (raw >> 63) & 1 else -1.0


def hashing_embed(text: str, dim: int = 384) -> list[float]:
    """Deterministic unit vector. Empty input yields a zero vector."""
    counts: dict[int, float] = {}
    for feat, weight in _features(text or ""):
        idx, sign = _bucket(feat, dim)
        counts[idx] = counts.get(idx, 0.0) + sign * weight

    vec = [0.0] * dim
    for idx, raw in counts.items():
        # Sublinear TF: a term appearing 50 times is not 50x as meaningful.
        vec[idx] = math.copysign(1.0 + math.log(abs(raw)), raw) if raw else 0.0

    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class Embedder:
    """Provider-dispatching embedder. Falls back to hashing on any failure."""

    GEMINI_URL = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "text-embedding-004:embedContent"
    )

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self.dim = self.settings.embedding_dim
        self._client = client

    async def embed(self, text: str) -> list[float]:
        if self.settings.embedding_provider == "gemini" and self.settings.gemini_api_key:
            try:
                return await self._gemini(text)
            except Exception as exc:  # network, quota, schema drift
                import logging

                logging.getLogger(__name__).warning(
                    "gemini embedding failed, falling back to hashing: %s", exc
                )
        return hashing_embed(text, self.dim)

    async def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]

    async def _gemini(self, text: str) -> list[float]:
        client = self._client or httpx.AsyncClient(timeout=self.settings.http_timeout_s)
        try:
            resp = await client.post(
                self.GEMINI_URL,
                params={"key": self.settings.gemini_api_key},
                json={
                    "model": "models/text-embedding-004",
                    "content": {"parts": [{"text": text[:8000]}]},
                    "outputDimensionality": self.dim,
                },
            )
            resp.raise_for_status()
            values = resp.json()["embedding"]["values"]
        finally:
            if self._client is None:
                await client.aclose()
        norm = math.sqrt(sum(v * v for v in values))
        return [v / norm for v in values] if norm else values
