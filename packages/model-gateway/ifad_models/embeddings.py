"""Deterministic offline embedder for tests and the local demo.

Ported from SupplyChain_Predictions backend/scinsight/rag.py::HashEmbedder @ 5c8dce6 (same idea as the Banking
copilot's _local_hash_embedding). Changes: light stemming, a stop-word list and word bigrams for better ranking.
It is a bag-of-words hash, not a semantic model: synonyms do not match. Measured quality is in TEST_RESULTS.md.
"""
from __future__ import annotations

import hashlib
import math
import re

STOP = frozenset("a an and are as at be by for from has have in is it its of on or that the this to was were will with "
                 "what which who how when where does do did not no any all our their there".split())


def _stem(token: str) -> str:
    for suffix in ("ations", "ation", "ings", "ing", "ies", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return token


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


class HashEmbedder:
    def __init__(self, dim: int = 384):
        self.dim = dim
        self.name = f"hash-bow-{dim}"

    def _add(self, vector: list[float], feature: str, weight: float) -> None:
        digest = hashlib.sha256(feature.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % self.dim
        vector[index] += weight if digest[4] & 1 else -weight

    def embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        tokens = tokenize(text)
        for token in tokens:
            self._add(vector, token, 1.0)
        for left, right in zip(tokens, tokens[1:], strict=False):
            self._add(vector, f"{left}_{right}", 0.5)
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]
