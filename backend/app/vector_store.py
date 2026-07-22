import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field


SUPPORTED_VECTOR_STORES = {"sqlite", "pgvector"}
MAX_PGVECTOR_DIMENSIONS = 2000
_pool_lock = threading.Lock()
_pool = None
_pool_key: tuple | None = None


class VectorStoreConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChunkVector:
    chunk_id: int
    document_id: int
    embedding_model: str
    content_hash: str
    embedding: list[float]


@dataclass(frozen=True)
class VectorStoreResult:
    backend: str
    status: str
    count: int = 0
    error: str | None = None
    scores: dict[int, float] = field(default_factory=dict)

    def public_dict(self) -> dict:
        result = {"backend": self.backend, "status": self.status, "count": self.count}
        if self.error:
            result["error"] = self.error
        return result


def vector_store_backend() -> str:
    backend = os.getenv("RAG_VECTOR_STORE", "sqlite").strip().lower() or "sqlite"
    if backend not in SUPPORTED_VECTOR_STORES:
        choices = ", ".join(sorted(SUPPORTED_VECTOR_STORES))
        raise VectorStoreConfigurationError(f"RAG_VECTOR_STORE must be one of: {choices}")
    return backend


def vector_store_fallback_enabled() -> bool:
    return os.getenv("RAG_VECTOR_STORE_FALLBACK", "true").strip().lower() in {"1", "true", "yes", "on"}


def pgvector_dimensions() -> int:
    raw = os.getenv("PGVECTOR_DIMENSIONS", "").strip()
    if not raw:
        raise VectorStoreConfigurationError("PGVECTOR_DIMENSIONS is required when RAG_VECTOR_STORE=pgvector")
    try:
        dimensions = int(raw)
    except ValueError as exc:
        raise VectorStoreConfigurationError("PGVECTOR_DIMENSIONS must be an integer") from exc
    if dimensions < 1 or dimensions > MAX_PGVECTOR_DIMENSIONS:
        raise VectorStoreConfigurationError(
            f"PGVECTOR_DIMENSIONS must be between 1 and {MAX_PGVECTOR_DIMENSIONS}"
        )
    return dimensions


def pgvector_dsn() -> str:
    dsn = os.getenv("PGVECTOR_DSN", "").strip()
    if not dsn:
        raise VectorStoreConfigurationError("PGVECTOR_DSN is required when RAG_VECTOR_STORE=pgvector")
    return dsn


def sync_chunk_vectors(items: list[ChunkVector]) -> VectorStoreResult:
    try:
        backend = vector_store_backend()
    except VectorStoreConfigurationError as exc:
        return VectorStoreResult(backend="invalid", status="degraded", error=str(exc))
    if backend == "sqlite":
        return VectorStoreResult(backend="sqlite", status="local", count=len(items))
    usable = [item for item in items if item.embedding and item.embedding_model]
    if not usable:
        return VectorStoreResult(backend="pgvector", status="ready", count=0)
    try:
        dimensions = pgvector_dimensions()
        _validate_items(usable, dimensions)
        with _connect_pgvector(dimensions) as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO rag_chunk_embeddings(
                        chunk_id, document_id, embedding_model, content_hash, embedding, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        document_id = EXCLUDED.document_id,
                        embedding_model = EXCLUDED.embedding_model,
                        content_hash = EXCLUDED.content_hash,
                        embedding = EXCLUDED.embedding,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    [
                        (
                            item.chunk_id,
                            item.document_id,
                            item.embedding_model,
                            item.content_hash,
                            item.embedding,
                        )
                        for item in usable
                    ],
                )
        return VectorStoreResult(backend="pgvector", status="ready", count=len(usable))
    except Exception as exc:
        return VectorStoreResult(backend="pgvector", status="degraded", error=_public_error(exc))


def query_chunk_vectors(
    query_embedding: list[float],
    embedding_model: str,
    allowed_chunk_ids: list[int],
    limit: int,
) -> VectorStoreResult:
    if not allowed_chunk_ids or not query_embedding:
        return VectorStoreResult(backend="pgvector", status="ready")
    try:
        dimensions = pgvector_dimensions()
        if len(query_embedding) != dimensions:
            raise VectorStoreConfigurationError(
                f"query embedding has {len(query_embedding)} dimensions; expected {dimensions}"
            )
        with _connect_pgvector(dimensions) as conn:
            conn.execute("SET LOCAL hnsw.iterative_scan = strict_order")
            rows = conn.execute(
                """
                SELECT chunk_id, 1 - (embedding <=> %s) AS similarity
                FROM rag_chunk_embeddings
                WHERE embedding_model = %s AND chunk_id = ANY(%s)
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (query_embedding, embedding_model, allowed_chunk_ids, query_embedding, max(1, limit)),
            ).fetchall()
        scores = {
            int(row[0]): max(0.0, min(1.0, float(row[1])))
            for row in rows
            if row[1] is not None
        }
        return VectorStoreResult(
            backend="pgvector",
            status="ready",
            count=len(scores),
            scores=scores,
        )
    except Exception as exc:
        return VectorStoreResult(backend="pgvector", status="degraded", error=_public_error(exc))


def delete_document_vectors(document_id: int) -> VectorStoreResult:
    try:
        backend = vector_store_backend()
    except VectorStoreConfigurationError as exc:
        return VectorStoreResult(backend="invalid", status="degraded", error=str(exc))
    if backend == "sqlite":
        return VectorStoreResult(backend="sqlite", status="local")
    try:
        dimensions = pgvector_dimensions()
        with _connect_pgvector(dimensions) as conn:
            cursor = conn.execute(
                "DELETE FROM rag_chunk_embeddings WHERE document_id = %s",
                (document_id,),
            )
            count = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        return VectorStoreResult(backend="pgvector", status="ready", count=count)
    except Exception as exc:
        return VectorStoreResult(backend="pgvector", status="degraded", error=_public_error(exc))


def vector_store_health() -> VectorStoreResult:
    try:
        backend = vector_store_backend()
    except VectorStoreConfigurationError as exc:
        return VectorStoreResult(backend="invalid", status="degraded", error=str(exc))
    if backend == "sqlite":
        return VectorStoreResult(backend="sqlite", status="ready")
    try:
        dimensions = pgvector_dimensions()
        with _connect_pgvector(dimensions) as conn:
            conn.execute("SELECT 1 FROM rag_chunk_embeddings LIMIT 1").fetchone()
        return VectorStoreResult(backend="pgvector", status="ready")
    except Exception as exc:
        return VectorStoreResult(backend="pgvector", status="degraded", error=_public_error(exc))


def close_vector_store_pool() -> None:
    global _pool, _pool_key
    with _pool_lock:
        if _pool is not None:
            _pool.close()
        _pool = None
        _pool_key = None


def _validate_items(items: list[ChunkVector], dimensions: int) -> None:
    for item in items:
        if len(item.embedding) != dimensions:
            raise VectorStoreConfigurationError(
                f"chunk {item.chunk_id} embedding has {len(item.embedding)} dimensions; expected {dimensions}"
            )


@contextmanager
def _connect_pgvector(dimensions: int):
    pool = _get_pgvector_pool(dimensions)
    with pool.connection() as conn:
        yield conn


def _get_pgvector_pool(dimensions: int):
    global _pool, _pool_key
    from psycopg_pool import ConnectionPool

    dsn = pgvector_dsn()
    timeout = _positive_int_env("PGVECTOR_CONNECT_TIMEOUT_SECONDS", 5)
    min_size = _positive_int_env("PGVECTOR_POOL_MIN_SIZE", 1)
    max_size = max(min_size, _positive_int_env("PGVECTOR_POOL_MAX_SIZE", 5))
    key = (dsn, dimensions, timeout, min_size, max_size)
    with _pool_lock:
        if _pool is not None and _pool_key == key:
            return _pool
        if _pool is not None:
            _pool.close()
        _initialize_pgvector(dsn, dimensions, timeout)
        pool = ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
            kwargs={"connect_timeout": timeout},
            configure=_configure_pgvector_connection,
            open=True,
        )
        try:
            pool.wait(timeout=timeout + 2)
        except Exception:
            pool.close()
            raise
        _pool = pool
        _pool_key = key
        return pool


def _configure_pgvector_connection(conn) -> None:
    from pgvector.psycopg import register_vector

    register_vector(conn)
    conn.commit()


def _initialize_pgvector(dsn: str, dimensions: int, timeout: int) -> None:
    import psycopg
    from pgvector.psycopg import register_vector

    with psycopg.connect(dsn, connect_timeout=timeout) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_vector_store_metadata (
                store_key TEXT PRIMARY KEY,
                dimensions INTEGER NOT NULL,
                schema_version INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO rag_vector_store_metadata(store_key, dimensions, schema_version)
            VALUES ('chunk_embeddings', %s, 1)
            ON CONFLICT (store_key) DO NOTHING
            """,
            (dimensions,),
        )
        configured = conn.execute(
            "SELECT dimensions FROM rag_vector_store_metadata WHERE store_key = 'chunk_embeddings'"
        ).fetchone()[0]
        if configured != dimensions:
            raise VectorStoreConfigurationError(
                f"pgvector store uses {configured} dimensions; configured value is {dimensions}"
            )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS rag_chunk_embeddings (
                chunk_id BIGINT PRIMARY KEY,
                document_id BIGINT NOT NULL,
                embedding_model TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                embedding vector({dimensions}) NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rag_chunk_embeddings_document
            ON rag_chunk_embeddings(document_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rag_chunk_embeddings_model
            ON rag_chunk_embeddings(embedding_model)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rag_chunk_embeddings_hnsw_cosine
            ON rag_chunk_embeddings USING hnsw (embedding vector_cosine_ops)
            """
        )


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _public_error(exc: Exception) -> str:
    if isinstance(exc, VectorStoreConfigurationError):
        return str(exc)
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return "pgvector_dependency_missing"
    return "pgvector_unavailable"
