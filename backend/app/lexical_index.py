import sqlite3
from dataclasses import dataclass, field

from .config import positive_int_env
from .text_processing import tokenize


LEXICAL_INDEX_NAME = "chunk_fts"
LEXICAL_INDEX_VERSION = 1
MAX_QUERY_TERMS = 32
MAX_CANDIDATE_LIMIT = 2000
SYNC_TRIGGER_NAMES = (
    "chunks_fts_after_insert",
    "chunks_fts_after_delete",
    "chunks_fts_after_update",
    "documents_fts_after_title_update",
    "documents_fts_after_delete",
)


@dataclass(frozen=True)
class LexicalSearchResult:
    backend: str
    status: str
    chunk_ids: list[int] = field(default_factory=list)
    error: str | None = None

    def public_dict(self) -> dict:
        result = {"backend": self.backend, "status": self.status}
        if self.error:
            result["error"] = self.error
        return result


def fts_token_text(value: str | None) -> str:
    return " ".join(tokenize(value or ""))


def lexical_candidate_limit(top_k: int) -> int:
    configured = positive_int_env("RAG_LEXICAL_CANDIDATE_LIMIT", 200)
    return max(top_k, min(configured, MAX_CANDIDATE_LIMIT))


def ensure_lexical_index(conn: sqlite3.Connection) -> LexicalSearchResult:
    try:
        index_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (LEXICAL_INDEX_NAME,),
        ).fetchone()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_index_metadata (
                index_name TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
                title_tokens,
                content_tokens,
                tokenize = 'unicode61'
            )
            """
        )
        _create_sync_triggers(conn)
        metadata = conn.execute(
            "SELECT version FROM search_index_metadata WHERE index_name = ?",
            (LEXICAL_INDEX_NAME,),
        ).fetchone()
        if not index_exists or not metadata or int(metadata["version"]) != LEXICAL_INDEX_VERSION:
            rebuild_lexical_index(conn)
        return LexicalSearchResult(backend="sqlite_fts5", status="ready")
    except sqlite3.Error as exc:
        return LexicalSearchResult(
            backend="full_scan",
            status="degraded",
            error=_public_error(exc),
        )


def rebuild_lexical_index(conn: sqlite3.Connection) -> int:
    conn.execute("DELETE FROM chunk_fts")
    conn.execute(
        """
        INSERT INTO chunk_fts(rowid, title_tokens, content_tokens)
        SELECT c.id, rag_fts_tokens(d.title), rag_fts_tokens(c.content)
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        ORDER BY c.id
        """
    )
    conn.execute(
        """
        INSERT INTO search_index_metadata(index_name, version, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(index_name) DO UPDATE SET
            version = excluded.version,
            updated_at = CURRENT_TIMESTAMP
        """,
        (LEXICAL_INDEX_NAME, LEXICAL_INDEX_VERSION),
    )
    return int(conn.execute("SELECT COUNT(*) AS count FROM chunk_fts").fetchone()["count"])


def lexical_index_health(conn: sqlite3.Connection) -> LexicalSearchResult:
    try:
        conn.execute("SELECT rowid FROM chunk_fts LIMIT 1").fetchone()
        placeholders = ",".join("?" for _ in SYNC_TRIGGER_NAMES)
        trigger_count = int(
            conn.execute(
                f"SELECT COUNT(*) AS count FROM sqlite_master WHERE type = 'trigger' AND name IN ({placeholders})",
                SYNC_TRIGGER_NAMES,
            ).fetchone()["count"]
        )
        if trigger_count != len(SYNC_TRIGGER_NAMES):
            return LexicalSearchResult(
                backend="full_scan",
                status="degraded",
                error="lexical_sync_triggers_missing",
            )
        return LexicalSearchResult(backend="sqlite_fts5", status="ready")
    except sqlite3.Error as exc:
        return LexicalSearchResult(
            backend="full_scan",
            status="degraded",
            error=_public_error(exc),
        )


def search_lexical_candidates(
    conn: sqlite3.Connection,
    question: str,
    access_levels: list[str],
    limit: int,
) -> LexicalSearchResult:
    health = lexical_index_health(conn)
    if health.status != "ready":
        return health
    query = _match_query(question)
    if not query:
        return LexicalSearchResult(backend="sqlite_fts5", status="ready")
    placeholders = ",".join("?" for _ in access_levels)
    try:
        rows = conn.execute(
            f"""
            SELECT chunk_fts.rowid AS chunk_id
            FROM chunk_fts
            JOIN chunks c ON c.id = chunk_fts.rowid
            JOIN documents d ON d.id = c.document_id
            WHERE chunk_fts MATCH ?
              AND d.access_level IN ({placeholders})
              AND d.status = 'ready'
            ORDER BY bm25(chunk_fts, 3.0, 7.0), chunk_fts.rowid DESC
            LIMIT ?
            """,
            (query, *access_levels, max(1, min(limit, MAX_CANDIDATE_LIMIT))),
        ).fetchall()
        return LexicalSearchResult(
            backend="sqlite_fts5",
            status="ready",
            chunk_ids=[int(row["chunk_id"]) for row in rows],
        )
    except sqlite3.Error as exc:
        return LexicalSearchResult(
            backend="full_scan",
            status="degraded",
            error=_public_error(exc),
        )


def _create_sync_triggers(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TRIGGER IF EXISTS chunks_fts_after_insert;
        DROP TRIGGER IF EXISTS chunks_fts_after_delete;
        DROP TRIGGER IF EXISTS chunks_fts_after_update;
        DROP TRIGGER IF EXISTS documents_fts_after_title_update;
        DROP TRIGGER IF EXISTS documents_fts_after_delete;

        CREATE TRIGGER chunks_fts_after_insert
        AFTER INSERT ON chunks
        BEGIN
            INSERT INTO chunk_fts(rowid, title_tokens, content_tokens)
            SELECT NEW.id, rag_fts_tokens(d.title), rag_fts_tokens(NEW.content)
            FROM documents d
            WHERE d.id = NEW.document_id;
        END;

        CREATE TRIGGER chunks_fts_after_delete
        AFTER DELETE ON chunks
        BEGIN
            DELETE FROM chunk_fts WHERE rowid = OLD.id;
        END;

        CREATE TRIGGER chunks_fts_after_update
        AFTER UPDATE OF document_id, content ON chunks
        BEGIN
            DELETE FROM chunk_fts WHERE rowid = OLD.id;
            INSERT INTO chunk_fts(rowid, title_tokens, content_tokens)
            SELECT NEW.id, rag_fts_tokens(d.title), rag_fts_tokens(NEW.content)
            FROM documents d
            WHERE d.id = NEW.document_id;
        END;

        CREATE TRIGGER documents_fts_after_title_update
        AFTER UPDATE OF title ON documents
        BEGIN
            UPDATE chunk_fts
            SET title_tokens = rag_fts_tokens(NEW.title)
            WHERE rowid IN (SELECT id FROM chunks WHERE document_id = NEW.id);
        END;

        CREATE TRIGGER documents_fts_after_delete
        AFTER DELETE ON documents
        BEGIN
            DELETE FROM chunk_fts
            WHERE rowid IN (SELECT id FROM chunks WHERE document_id = OLD.id);
        END;
        """
    )


def _match_query(question: str) -> str:
    unique_terms = list(dict.fromkeys(tokenize(question)))
    prioritized = sorted(unique_terms, key=lambda term: (len(term) == 1, -len(term)))[:MAX_QUERY_TERMS]
    return " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in prioritized)


def _public_error(exc: Exception) -> str:
    message = str(exc).strip()
    return message[:160] if message else exc.__class__.__name__
