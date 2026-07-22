import os

import pytest

from app.vector_store import (
    ChunkVector,
    delete_document_vectors,
    query_chunk_vectors,
    sync_chunk_vectors,
    vector_store_health,
)


pytestmark = pytest.mark.skipif(
    not os.getenv("PGVECTOR_TEST_DSN"),
    reason="PGVECTOR_TEST_DSN is required for the pgvector integration suite",
)


def configure_pgvector(monkeypatch):
    monkeypatch.setenv("RAG_VECTOR_STORE", "pgvector")
    monkeypatch.setenv("RAG_VECTOR_STORE_FALLBACK", "false")
    monkeypatch.setenv("PGVECTOR_DSN", os.environ["PGVECTOR_TEST_DSN"])
    monkeypatch.setenv("PGVECTOR_DIMENSIONS", "3")


def test_pgvector_upsert_acl_candidate_filter_and_delete(monkeypatch):
    configure_pgvector(monkeypatch)
    delete_document_vectors(91001)
    delete_document_vectors(91002)

    sync = sync_chunk_vectors(
        [
            ChunkVector(910011, 91001, "integration-demo", "a", [1.0, 0.0, 0.0]),
            ChunkVector(910012, 91001, "integration-demo", "b", [0.8, 0.2, 0.0]),
            ChunkVector(910021, 91002, "integration-demo", "restricted", [0.99, 0.01, 0.0]),
        ]
    )

    assert sync.status == "ready", sync.diagnostic
    assert sync.count == 3
    allowed = query_chunk_vectors(
        [1.0, 0.0, 0.0],
        "integration-demo",
        [91001],
        5,
    )
    assert allowed.status == "ready", allowed.diagnostic
    assert list(allowed.scores)[0] == 910011
    assert 910021 not in allowed.scores

    updated = sync_chunk_vectors(
        [ChunkVector(910012, 91001, "integration-demo", "updated", [1.0, 0.0, 0.0])]
    )
    assert updated.status == "ready", updated.diagnostic
    exact = query_chunk_vectors([1.0, 0.0, 0.0], "integration-demo", [91001], 2)
    assert exact.scores[910012] == pytest.approx(1.0)
    assert 910021 not in exact.scores

    deleted = delete_document_vectors(91001)
    assert deleted.status == "ready"
    assert deleted.count == 2
    after_delete = query_chunk_vectors([1.0, 0.0, 0.0], "integration-demo", [91001], 5)
    assert after_delete.scores == {}
    delete_document_vectors(91002)


def test_pgvector_health_and_dimension_guard(monkeypatch):
    configure_pgvector(monkeypatch)

    assert vector_store_health().status == "ready"
    mismatch = sync_chunk_vectors(
        [ChunkVector(920011, 92001, "integration-demo", "bad", [1.0, 0.0])]
    )
    assert mismatch.status == "degraded"
    assert "expected 3" in mismatch.error
