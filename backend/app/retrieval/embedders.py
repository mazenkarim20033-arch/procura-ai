"""Embedder implementations and factory."""
import hashlib
import math
import re
from functools import lru_cache

from app.config import Settings, get_settings

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class FastEmbedEmbedder:
    """ONNX-based local embeddings (no torch). Model downloads on first use (~130 MB for bge-small)."""

    def __init__(self, model_name: str, dim: int, query_prefix: bool = True, cache_dir: str | None = None):
        self.name = model_name
        self.dim = dim
        self._cache_dir = cache_dir
        self._query_prefix = query_prefix and "bge" in model_name.lower()
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.name, cache_dir=self._cache_dir)
        return self._model

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._load().embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        prefixed = BGE_QUERY_PREFIX + text if self._query_prefix else text
        return next(iter(self._load().embed([prefixed]))).tolist()


class HashingEmbedder:
    """Deterministic bag-of-words hashing vectors. NOT semantic: exists so tests and CI can run the
    full pipeline without downloading a model. Never use for real retrieval quality claims."""

    name = "hashing-test-only"

    def __init__(self, dim: int = 384):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0 if (h >> 20) % 2 else -1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def build_embedder(settings: Settings):
    if settings.embedding_provider == "hashing":
        return HashingEmbedder(settings.embedding_dim)
    if settings.embedding_provider == "fastembed":
        return FastEmbedEmbedder(settings.embedding_model, settings.embedding_dim,
                                 settings.embedding_query_prefix, settings.embedding_cache_dir)
    raise ValueError(f"Unknown embedding provider: {settings.embedding_provider}")


@lru_cache
def get_embedder():
    return build_embedder(get_settings())
