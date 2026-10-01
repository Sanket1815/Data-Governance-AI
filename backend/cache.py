from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from redisvl.extensions.cache.llm import SemanticCache
from redisvl.utils.vectorize import BaseVectorizer, GoogleGenAIVectorizer, OpenAITextVectorizer

from config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CachedQueryResult:
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    estimated_bytes: int


def _build_default_vectorizer(settings: Settings) -> BaseVectorizer:
    """Reuses the same embedding provider as query_engine.py rather than pulling in a local
    sentence-transformers/PyTorch install just for the cache's similarity lookups."""
    if settings.llm_provider == "gemini":
        return GoogleGenAIVectorizer(
            model=settings.embedding_model,
            api_config={"api_key": settings.google_api_key},
        )
    return OpenAITextVectorizer(
        model="text-embedding-3-small",
        api_config={"api_key": settings.openai_api_key},
    )


class SemanticCacheService:
    """Wraps a RedisVL SemanticCache to short-circuit LLM calls for semantically similar prior prompts."""

    def __init__(self, settings: Settings | None = None, vectorizer: BaseVectorizer | None = None) -> None:
        self._settings = settings or get_settings()
        self._vectorizer = vectorizer or _build_default_vectorizer(self._settings)
        self._cache: SemanticCache | None = None
        try:
            self._cache = SemanticCache(
                name="nl2sql_semantic_cache",
                redis_url=self._settings.redis_url,
                vectorizer=self._vectorizer,
                distance_threshold=self._settings.semantic_cache_distance_threshold,
                ttl=self._settings.redis_cache_ttl_seconds,
            )
        except Exception:
            logger.warning(
                "Semantic cache unavailable (check REDIS_URL and Redis Stack); continuing without cache.",
                exc_info=True,
            )

    def lookup(self, user_prompt: str) -> CachedQueryResult | None:
        if self._cache is None:
            return None
        try:
            matches = self._cache.check(prompt=user_prompt, num_results=1)
        except Exception:
            logger.warning("Semantic cache lookup failed; falling back to live query.", exc_info=True)
            return None

        if not matches:
            return None

        try:
            payload = json.loads(matches[0]["response"])
            return CachedQueryResult(
                sql=payload["sql"],
                columns=payload["columns"],
                rows=payload["rows"],
                estimated_bytes=payload["estimated_bytes"],
            )
        except (KeyError, json.JSONDecodeError):
            logger.warning("Malformed cache entry encountered; ignoring.", exc_info=True)
            return None

    def store(self, user_prompt: str, result: CachedQueryResult) -> None:
        payload = json.dumps(
            {
                "sql": result.sql,
                "columns": result.columns,
                "rows": result.rows,
                "estimated_bytes": result.estimated_bytes,
            },
            default=str,
        )
        if self._cache is None:
            return
        try:
            self._cache.store(prompt=user_prompt, response=payload)
        except Exception:
            logger.warning("Failed to write to semantic cache; continuing without caching this result.", exc_info=True)

    def clear(self) -> None:
        if self._cache is None:
            return
        self._cache.clear()
