import json

from app import embeddings, main
from app.db import get_conn
from app.vector_store import VectorStoreResult


def test_embedding_is_disabled_without_explicit_model(monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)

    result = embeddings.build_chunk_index(["片段一", "片段二"])

    assert result.status == "not_configured"
    assert result.model is None
    assert [item.embedding for item in result.items] == [[], []]
    assert all(item.content_hash for item in result.items)


def test_embedding_batch_is_attached_to_chunk_index(monkeypatch):
    monkeypatch.setattr(
        embeddings,
        "embed_texts",
        lambda texts, model=None: embeddings.EmbeddingBatch(
            status="ready",
            model=model or "demo-embedding",
            vectors=[[float(index), 1.0] for index, _ in enumerate(texts, start=1)],
        ),
    )

    result = embeddings.build_chunk_index(["片段一", "片段二"], model="demo-embedding")

    assert result.status == "ready"
    assert result.model == "demo-embedding"
    assert result.items[0].embedding == [1.0, 1.0]
    assert json.loads(result.items[0].token_json)
    assert result.items[0].content_hash != result.items[1].content_hash


def test_document_upload_persists_embedding_index_status(client, admin_headers, monkeypatch):
    real_builder = embeddings.build_chunk_index
    synced = []

    def fake_builder(chunks, model=None):
        base = real_builder(chunks, model=None)
        items = [
            embeddings.ChunkIndexItem(
                content=item.content,
                token_json=item.token_json,
                content_hash=item.content_hash,
                embedding=[0.25, 0.75],
            )
            for item in base.items
        ]
        return embeddings.ChunkIndex(status="ready", model="demo-embedding", items=items)

    monkeypatch.setattr(main, "build_chunk_index", fake_builder)
    monkeypatch.setattr(
        main,
        "sync_chunk_vectors",
        lambda items: synced.extend(items)
        or VectorStoreResult(backend="pgvector", status="ready", count=len(items)),
    )

    response = client.post(
        "/api/documents/upload",
        headers=admin_headers,
        data={"access_level": "internal"},
        files={"file": ("policy.md", "员工差旅住宿按城市等级执行。".encode(), "text/markdown")},
    )

    assert response.status_code == 200
    assert response.json()["embedding_status"] == "ready"
    assert response.json()["embedding_model"] == "demo-embedding"
    assert response.json()["embedding_gateway"] == {
        "attempts": 0,
        "latency_ms": 0,
        "status_code": None,
        "error": None,
    }
    assert response.json()["vector_store"]["status"] == "ready"
    with get_conn() as conn:
        document = conn.execute(
            "SELECT embedding_status, embedding_model FROM documents WHERE id = ?",
            (response.json()["id"],),
        ).fetchone()
        chunk = conn.execute(
            "SELECT embedding_json, embedding_model, content_hash FROM chunks WHERE document_id = ?",
            (response.json()["id"],),
        ).fetchone()
    assert document["embedding_status"] == "ready"
    assert document["embedding_model"] == "demo-embedding"
    assert json.loads(chunk["embedding_json"]) == [0.25, 0.75]
    assert chunk["embedding_model"] == "demo-embedding"
    assert chunk["content_hash"]
    assert len(synced) == 1
    assert synced[0].document_id == response.json()["id"]


def test_bulk_embedding_rebuild_updates_existing_chunks(client, admin_headers, monkeypatch):
    with get_conn() as conn:
        document_id = conn.execute(
            """
            INSERT INTO documents(
                title, filename, file_type, storage_path, access_level,
                status, chunk_count, version, embedding_status, created_at
            )
            VALUES ('旧文档', 'legacy.md', 'md', 'test', 'internal', 'ready', 1, 1, 'not_configured', datetime('now'))
            """
        ).lastrowid
        conn.execute(
            """
            INSERT INTO chunks(document_id, chunk_index, content, token_json, created_at)
            VALUES (?, 0, '旧文档中的报销规则', '{}', datetime('now'))
            """,
            (document_id,),
        )

    def fake_builder(chunks, model=None):
        return embeddings.ChunkIndex(
            status="ready",
            model="demo-embedding",
            items=[
                embeddings.ChunkIndexItem(
                    content=chunks[0],
                    token_json='{"报销": 1}',
                    content_hash="new-hash",
                    embedding=[0.4, 0.6],
                )
            ],
        )

    monkeypatch.setenv("EMBEDDING_MODEL", "demo-embedding")
    monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(main, "build_chunk_index", fake_builder)

    response = client.post(
        "/api/documents/embeddings/rebuild",
        headers=admin_headers,
        json={"document_ids": [document_id], "force": True},
    )

    assert response.status_code == 200
    assert response.json()["indexed"] == 1
    with get_conn() as conn:
        document = conn.execute(
            "SELECT embedding_status, embedding_model FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        chunk = conn.execute(
            "SELECT embedding_json, content_hash FROM chunks WHERE document_id = ?", (document_id,)
        ).fetchone()
    assert tuple(document) == ("ready", "demo-embedding")
    assert json.loads(chunk["embedding_json"]) == [0.4, 0.6]
    assert chunk["content_hash"] == "new-hash"
