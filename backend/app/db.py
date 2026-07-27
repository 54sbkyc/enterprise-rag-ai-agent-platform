import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .config import DB_PATH
from .evaluation_dataset import load_evaluation_dataset
from .lexical_index import ensure_lexical_index, fts_token_text
from .migrations import apply_migrations


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.create_function("rag_fts_tokens", 1, fts_token_text, deterministic=True)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        apply_migrations(conn)
        ensure_lexical_index(conn)
        from .permissions import seed_default_permissions

        seed_default_permissions(conn)
        _seed_document_versions(conn)
        _seed_evaluation_cases(conn)

    from .auth import seed_default_users

    seed_default_users()


def _seed_document_versions(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT COUNT(*) AS count FROM document_versions").fetchone()["count"]
    if existing:
        return
    rows = conn.execute(
        """
        SELECT id, version, title, access_level, chunk_count, created_at
        FROM documents
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT INTO document_versions(document_id, version, action, title, access_level, chunk_count, created_at)
            VALUES (?, ?, 'initial', ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["version"],
                row["title"],
                row["access_level"],
                row["chunk_count"],
                row["created_at"],
            ),
        )


def _seed_evaluation_cases(conn: sqlite3.Connection) -> None:
    dataset = load_evaluation_dataset()
    legacy_questions = {
        "contract-approval-materials": ["核心合作合同审批需要提交哪些材料？", "合同总价是多少？"],
    }
    for case in dataset["cases"]:
        candidates = [case["question"], *legacy_questions.get(case["key"], [])]
        existing = conn.execute(
            "SELECT id FROM evaluation_cases WHERE case_key = ? LIMIT 1",
            (case["key"],),
        ).fetchone()
        if not existing:
            placeholders = ",".join("?" for _ in candidates)
            existing = conn.execute(
                f"""
                SELECT id
                FROM evaluation_cases
                WHERE case_key IS NULL AND question IN ({placeholders})
                ORDER BY CASE WHEN question = ? THEN 0 ELSE 1 END, id
                LIMIT 1
                """,
                (*candidates, case["question"]),
            ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE evaluation_cases
                SET case_key = ?, dataset_version = ?, category = ?, actor_role = ?, question = ?,
                    expected_keywords = ?, expected_documents = ?, should_answer = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    case["key"],
                    dataset["version"],
                    case["category"],
                    case["actor_role"],
                    case["question"],
                    json.dumps(case["expected_keywords"], ensure_ascii=False),
                    json.dumps(case["expected_documents"], ensure_ascii=False),
                    1 if case["should_answer"] else 0,
                    utc_now(),
                    existing["id"],
                ),
            )
            continue
        conn.execute(
            """
            INSERT INTO evaluation_cases(
                case_key, dataset_version, category, actor_role, question,
                expected_keywords, expected_documents, should_answer, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case["key"],
                dataset["version"],
                case["category"],
                case["actor_role"],
                case["question"],
                json.dumps(case["expected_keywords"], ensure_ascii=False),
                json.dumps(case["expected_documents"], ensure_ascii=False),
                1 if case["should_answer"] else 0,
                utc_now(),
                utc_now(),
            ),
        )
