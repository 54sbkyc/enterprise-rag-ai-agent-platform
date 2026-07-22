import json

import pytest

from app import main, search
from app.db import get_conn, utc_now
from app.text_processing import token_counts
from app.vector_store import (
    ChunkVector,
    VectorStoreConfigurationError,
    VectorStoreResult,
    pgvector_dimensions,
    sync_chunk_vectors,
    vector_store_backend,
)


def insert_vector_chunk(title: str, embedding: list[float]) -> int:
    with get_conn() as conn:
        document_id = conn.execute(
            """
            INSERT INTO documents(
                title, filename, file_type, storage_path, access_level,
                status, chunk_count, version, created_at
            )
            VALUES (?, ?, 'md', 'test', 'internal', 'ready', 1, 1, ?)
            """,
            (title, f"{title}.md", utc_now()),
        ).lastrowid
        return conn.execute(
            """
            INSERT INTO chunks(
                document_id, chunk_index, content, token_json,
                embedding_json, embedding_model, content_hash, created_at
            )
            VALUES (?, 0, ?, ?, ?, 'demo', 'hash', ?)
            """,
            (
                document_id,
                title,
                json.dumps(token_counts(title), ensure_ascii=False),
                json.dumps(embedding),
                utc_now(),
            ),
        ).lastrowid


def test_vector_store_configuration_is_explicit(monkeypatch):
    monkeypatch.setenv("RAG_VECTOR_STORE", " PGVECTOR ")
    monkeypatch.setenv("PGVECTOR_DIMENSIONS", "768")

    assert vector_store_backend() == "pgvector"
    assert pgvector_dimensions() == 768

    monkeypatch.setenv("RAG_VECTOR_STORE", "unknown")
    with pytest.raises(VectorStoreConfigurationError, match="RAG_VECTOR_STORE"):
        vector_store_backend()

    monkeypatch.setenv("PGVECTOR_DIMENSIONS", "2001")
    with pytest.raises(VectorStoreConfigurationError, match="between 1 and 2000"):
        pgvector_dimensions()


def test_sqlite_vector_store_keeps_zero_service_default():
    result = sync_chunk_vectors(
        [
            ChunkVector(
                chunk_id=1,
                document_id=1,
                embedding_model="demo",
                content_hash="hash",
                embedding=[1.0, 0.0],
            )
        ]
    )

    assert result == VectorStoreResult(backend="sqlite", status="local", count=1)


def test_pgvector_outage_falls_back_to_local_vectors_and_is_visible(monkeypatch):
    best_id = insert_vector_chunk("semantic policy", [1.0, 0.0])
    insert_vector_chunk("unrelated device", [0.0, 1.0])
    monkeypatch.setenv("RAG_VECTOR_STORE", "pgvector")
    monkeypatch.setenv("RAG_VECTOR_STORE_FALLBACK", "true")
    monkeypatch.setattr(search, "embed_query", lambda _text, _model: [1.0, 0.0])
    monkeypatch.setattr(
        search,
        "query_chunk_vectors",
        lambda *_args, **_kwargs: VectorStoreResult(
            backend="pgvector",
            status="degraded",
            error="pgvector_unavailable",
        ),
    )

    hits = search.search_chunks("different wording", 5, ["internal"])

    assert hits[0].chunk_id == best_id
    assert hits[0].retrieval_mode == "hybrid"
    assert hits[0].vector_backend == "sqlite_fallback"
    assert hits[0].vector_degraded is True
    assert hits[0].vector_error == "pgvector_unavailable"


def test_pgvector_can_fail_closed_to_bm25(monkeypatch):
    insert_vector_chunk("policy keyword", [1.0, 0.0])
    monkeypatch.setenv("RAG_VECTOR_STORE", "pgvector")
    monkeypatch.setenv("RAG_VECTOR_STORE_FALLBACK", "false")
    monkeypatch.setattr(search, "embed_query", lambda _text, _model: [1.0, 0.0])
    monkeypatch.setattr(
        search,
        "query_chunk_vectors",
        lambda *_args, **_kwargs: VectorStoreResult(
            backend="pgvector",
            status="degraded",
            error="pgvector_unavailable",
        ),
    )

    hits = search.search_chunks("policy", 5, ["internal"])

    assert hits[0].retrieval_mode == "bm25"
    assert hits[0].vector_backend == "pgvector"
    assert hits[0].vector_degraded is True
    assert hits[0].vector_score == 0


def test_pgvector_query_receives_live_allowed_document_ids(monkeypatch):
    allowed_chunk_id = insert_vector_chunk("allowed policy", [1.0, 0.0])
    with get_conn() as conn:
        allowed_document_id = int(
            conn.execute("SELECT document_id FROM chunks WHERE id = ?", (allowed_chunk_id,)).fetchone()[0]
        )
        restricted_document_id = conn.execute(
            """
            INSERT INTO documents(
                title, filename, file_type, storage_path, access_level,
                status, chunk_count, version, created_at
            )
            VALUES ('restricted', 'restricted.md', 'md', 'test', 'sensitive', 'ready', 0, 1, ?)
            """,
            (utc_now(),),
        ).lastrowid
    captured = {}
    monkeypatch.setenv("RAG_VECTOR_STORE", "pgvector")
    monkeypatch.setattr(search, "embed_query", lambda _text, _model: [1.0, 0.0])

    def fake_query(_embedding, _model, document_ids, _limit):
        captured["document_ids"] = document_ids
        return VectorStoreResult(
            backend="pgvector",
            status="ready",
            scores={allowed_chunk_id: 1.0},
        )

    monkeypatch.setattr(search, "query_chunk_vectors", fake_query)

    hits = search.search_chunks("semantic wording", 5, ["internal"])

    assert hits[0].chunk_id == allowed_chunk_id
    assert captured["document_ids"] == [allowed_document_id]
    assert int(restricted_document_id) not in captured["document_ids"]


def test_admin_can_reconcile_existing_sqlite_vectors_without_provider_call(client, admin_headers, monkeypatch):
    chunk_id = insert_vector_chunk("existing vector", [0.25, 0.75])
    calls = {"deleted": [], "synced": []}
    monkeypatch.setattr(main, "vector_store_backend", lambda: "pgvector")
    monkeypatch.setattr(
        main,
        "delete_document_vectors",
        lambda document_id: calls["deleted"].append(document_id)
        or VectorStoreResult(backend="pgvector", status="ready", count=0),
    )
    monkeypatch.setattr(
        main,
        "sync_chunk_vectors",
        lambda items: calls["synced"].extend(items)
        or VectorStoreResult(backend="pgvector", status="ready", count=len(items)),
    )

    response = client.post(
        "/api/documents/vector-store/sync",
        headers=admin_headers,
        json={},
    )

    assert response.status_code == 200
    assert response.json()["indexed_documents"] == 1
    assert response.json()["indexed_chunks"] == 1
    assert calls["deleted"]
    assert calls["synced"][0].chunk_id == chunk_id
