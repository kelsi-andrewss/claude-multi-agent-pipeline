from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)

EMBEDDING_DIM = 256
MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"


@dataclass
class EmbeddingResult:
    vector: list[float]
    model: str
    dim: int


class EmbeddingProvider:
    def __init__(self, model_name: str = MODEL_NAME, dim: int = EMBEDDING_DIM) -> None:
        self._model_name = model_name
        self._dim = dim
        self._model = None
        self._available: bool | None = None

    def _ensure_model(self) -> bool:
        if self._available is not None:
            return self._available

        try:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self._model_name)
            self._available = True
        except ImportError:
            print(
                f"fastembed not installed; embedding provider unavailable",
                file=sys.stderr,
            )
            self._available = False
        except Exception as e:
            print(
                f"Failed to load embedding model {self._model_name}: {e}",
                file=sys.stderr,
            )
            self._available = False

        return self._available

    def available(self) -> bool:
        if self._available is None:
            self._ensure_model()
        return self._available

    def get_embedding(self, text: str) -> EmbeddingResult | None:
        if not self._ensure_model():
            return None

        try:
            results = list(self._model.query_embed(text))
            vector = results[0].tolist()
            vector = vector[: self._dim]
            return EmbeddingResult(
                vector=vector, model=self._model_name, dim=self._dim
            )
        except Exception as e:
            log.warning("Embedding generation failed: %s", e)
            return None

    def get_embeddings_batch(self, texts: list[str]) -> list[EmbeddingResult | None]:
        if not self._ensure_model():
            return [None] * len(texts)

        results: list[EmbeddingResult | None] = []
        try:
            for vector in self._model.embed(texts):
                v = vector.tolist()
                v = v[: self._dim]
                results.append(
                    EmbeddingResult(vector=v, model=self._model_name, dim=self._dim)
                )
        except Exception as e:
            log.warning("Batch embedding failed: %s", e)
            while len(results) < len(texts):
                results.append(None)

        return results


_default_provider: EmbeddingProvider | None = None


def get_default_provider() -> EmbeddingProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = EmbeddingProvider()
    return _default_provider
