import hashlib
import json
import os
from dataclasses import dataclass, field

from .provider_gateway import policy_from_env, post_json
from .text_processing import token_counts


@dataclass(frozen=True)
class EmbeddingBatch:
    status: str
    model: str | None
    vectors: list[list[float]] = field(default_factory=list)
    error: str | None = None
    provider_attempts: int = 0
    provider_latency_ms: int = 0
    provider_status_code: int | None = None


@dataclass(frozen=True)
class ChunkIndexItem:
    content: str
    token_json: str
    content_hash: str
    embedding: list[float]


@dataclass(frozen=True)
class ChunkIndex:
    status: str
    model: str | None
    items: list[ChunkIndexItem]
    error: str | None = None
    provider_attempts: int = 0
    provider_latency_ms: int = 0
    provider_status_code: int | None = None

    def provider_diagnostics(self) -> dict:
        return {
            "attempts": self.provider_attempts,
            "latency_ms": self.provider_latency_ms,
            "status_code": self.provider_status_code,
            "error": self.error,
        }


def build_chunk_index(chunks: list[str], model: str | None = None) -> ChunkIndex:
    effective_model = (model or os.getenv("EMBEDDING_MODEL", "")).strip() or None
    batch = (
        embed_texts(chunks, model=effective_model)
        if effective_model
        else EmbeddingBatch(status="not_configured", model=None)
    )
    vectors = batch.vectors if batch.status == "ready" and len(batch.vectors) == len(chunks) else [[] for _ in chunks]
    items = [
        ChunkIndexItem(
            content=content,
            token_json=json.dumps(token_counts(content), ensure_ascii=False),
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            embedding=[float(value) for value in vector],
        )
        for content, vector in zip(chunks, vectors)
    ]
    return ChunkIndex(
        status=batch.status,
        model=batch.model,
        items=items,
        error=batch.error,
        provider_attempts=batch.provider_attempts,
        provider_latency_ms=batch.provider_latency_ms,
        provider_status_code=batch.provider_status_code,
    )


def embed_query(text: str, model: str) -> list[float] | None:
    result = embed_texts([text], model=model)
    if result.status != "ready" or not result.vectors:
        return None
    return result.vectors[0]


def embed_texts(texts: list[str], model: str | None = None) -> EmbeddingBatch:
    effective_model = (model or os.getenv("EMBEDDING_MODEL", "")).strip()
    api_key = (os.getenv("EMBEDDING_API_KEY") or os.getenv("LLM_API_KEY") or "").strip()
    if not effective_model or not api_key:
        return EmbeddingBatch(status="not_configured", model=effective_model or None)
    if not texts:
        return EmbeddingBatch(status="ready", model=effective_model, vectors=[])

    base_url = (
        os.getenv("EMBEDDING_BASE_URL")
        or os.getenv("LLM_BASE_URL")
        or "https://api.openai.com/v1"
    ).rstrip("/")
    batch_size = _positive_int("EMBEDDING_BATCH_SIZE", 32)
    policy = policy_from_env("EMBEDDING", default_timeout_seconds=30, default_max_attempts=3)
    vectors: list[list[float]] = []
    provider_attempts = 0
    provider_latency_ms = 0
    provider_status_code: int | None = None

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = post_json(
            f"{base_url}/embeddings",
            payload={"model": effective_model, "input": batch},
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            policy=policy,
        )
        provider_attempts += response.attempts
        provider_latency_ms += response.latency_ms
        provider_status_code = response.status_code
        if not response.ready:
            return EmbeddingBatch(
                status="failed",
                model=effective_model,
                error=response.error,
                provider_attempts=provider_attempts,
                provider_latency_ms=provider_latency_ms,
                provider_status_code=provider_status_code,
            )
        try:
            payload = response.payload or {}
            raw_items = payload["data"]
            if not isinstance(raw_items, list) or any(not isinstance(item, dict) for item in raw_items):
                raise ValueError("embedding data must be a list of objects")
            ordered = sorted(raw_items, key=lambda item: int(item.get("index", 0)))
            batch_vectors = [[float(value) for value in item["embedding"]] for item in ordered]
            if len(batch_vectors) != len(batch):
                raise ValueError("embedding count mismatch")
            vectors.extend(batch_vectors)
        except (KeyError, TypeError, ValueError):
            return EmbeddingBatch(
                status="failed",
                model=effective_model,
                error="invalid_provider_response",
                provider_attempts=provider_attempts,
                provider_latency_ms=provider_latency_ms,
                provider_status_code=provider_status_code,
            )
    if vectors and len({len(vector) for vector in vectors}) != 1:
        return EmbeddingBatch(
            status="failed",
            model=effective_model,
            error="invalid_provider_response",
            provider_attempts=provider_attempts,
            provider_latency_ms=provider_latency_ms,
            provider_status_code=provider_status_code,
        )
    return EmbeddingBatch(
        status="ready",
        model=effective_model,
        vectors=vectors,
        provider_attempts=provider_attempts,
        provider_latency_ms=provider_latency_ms,
        provider_status_code=provider_status_code,
    )


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default
