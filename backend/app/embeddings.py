import hashlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .text_processing import token_counts


@dataclass(frozen=True)
class EmbeddingBatch:
    status: str
    model: str | None
    vectors: list[list[float]] = field(default_factory=list)
    error: str | None = None


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
    return ChunkIndex(status=batch.status, model=batch.model, items=items, error=batch.error)


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
    timeout = _positive_int("EMBEDDING_TIMEOUT_SECONDS", 30)
    vectors: list[list[float]] = []

    try:
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            request = urllib.request.Request(
                f"{base_url}/embeddings",
                data=json.dumps({"model": effective_model, "input": batch}, ensure_ascii=False).encode("utf-8"),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            ordered = sorted(payload["data"], key=lambda item: int(item.get("index", 0)))
            batch_vectors = [[float(value) for value in item["embedding"]] for item in ordered]
            if len(batch_vectors) != len(batch):
                raise ValueError("embedding count mismatch")
            vectors.extend(batch_vectors)
        if vectors and len({len(vector) for vector in vectors}) != 1:
            raise ValueError("embedding dimensions mismatch")
        return EmbeddingBatch(status="ready", model=effective_model, vectors=vectors)
    except urllib.error.URLError:
        return EmbeddingBatch(status="failed", model=effective_model, error="provider_unavailable")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return EmbeddingBatch(status="failed", model=effective_model, error="invalid_provider_response")


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default
