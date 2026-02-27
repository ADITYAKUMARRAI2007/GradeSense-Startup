"""Pluggable semantic similarity providers for continuity layer."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import List, Protocol

from app.config import (
    UNIVERSAL_CONTINUITY_SEMANTIC_PROVIDER,
    logger,
)


class EmbeddingProvider(Protocol):
    def embed(self, texts: List[str]) -> List[List[float]]:
        ...


class LocalLexicalEmbeddingProvider:
    """Deterministic lexical embedding fallback using token frequencies."""

    TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)

    def _tokens(self, text: str) -> List[str]:
        return [t.lower() for t in self.TOKEN_RE.findall(text or "")]

    def embed(self, texts: List[str]) -> List[List[float]]:
        vocab = {}
        tokenized = []
        for text in texts:
            toks = self._tokens(text)
            tokenized.append(toks)
            for tok in toks:
                if tok not in vocab:
                    vocab[tok] = len(vocab)
        dim = max(8, len(vocab))
        vectors: List[List[float]] = []
        for toks in tokenized:
            vec = [0.0] * dim
            for tok in toks:
                idx = vocab.get(tok)
                if idx is not None:
                    vec[idx] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


@dataclass
class GeminiEmbeddingProvider:
    model: str = "text-embedding-004"

    def embed(self, texts: List[str]) -> List[List[float]]:
        try:
            from google import genai

            client = genai.Client()
            vectors: List[List[float]] = []
            for text in texts:
                resp = client.models.embed_content(model=self.model, contents=[text or ""])
                emb = (resp.embeddings or [None])[0]
                values = list(getattr(emb, "values", []) or [])
                vectors.append([float(v) for v in values])
            return vectors
        except Exception as exc:
            raise RuntimeError(f"gemini_embedding_failed:{exc}") from exc


class SemanticEmbeddingService:
    """Provider selector with fallback chain."""

    def __init__(self) -> None:
        self.primary = UNIVERSAL_CONTINUITY_SEMANTIC_PROVIDER
        self.local = LocalLexicalEmbeddingProvider()
        self.gemini = GeminiEmbeddingProvider()

    def embed(self, texts: List[str]) -> List[List[float]]:
        if self.primary == "local":
            return self.local.embed(texts)
        try:
            return self.gemini.embed(texts)
        except Exception as exc:
            logger.warning("Universal continuity embedding fallback activated: %s", exc)
            return self.local.embed(texts)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n <= 0:
        return 0.0
    dot = sum(float(a[i]) * float(b[i]) for i in range(n))
    na = math.sqrt(sum(float(a[i]) * float(a[i]) for i in range(n)))
    nb = math.sqrt(sum(float(b[i]) * float(b[i]) for i in range(n)))
    if na == 0 or nb == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


__all__ = [
    "EmbeddingProvider",
    "LocalLexicalEmbeddingProvider",
    "GeminiEmbeddingProvider",
    "SemanticEmbeddingService",
    "cosine_similarity",
]
