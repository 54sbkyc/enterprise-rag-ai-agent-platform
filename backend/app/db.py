import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import DB_PATH
from .evaluation_dataset import load_evaluation_dataset


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    schema_path = Path(__file__).with_name("schema.sql")
    with get_conn() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        _ensure_column(conn, "documents", "access_level", "TEXT NOT NULL DEFAULT 'internal'")
        _ensure_column(conn, "documents", "version", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "documents", "embedding_status", "TEXT NOT NULL DEFAULT 'not_configured'")
        _ensure_column(conn, "documents", "embedding_model", "TEXT")
        _ensure_column(conn, "chunks", "embedding_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "chunks", "embedding_model", "TEXT")
        _ensure_column(conn, "chunks", "content_hash", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "qa_logs", "user_id", "INTEGER")
        _ensure_column(conn, "qa_logs", "agent_trace_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "qa_logs", "usage_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "evaluations", "user_id", "INTEGER")
        _ensure_column(conn, "evaluations", "expected_documents", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "evaluations", "citation_hit", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "evaluation_cases", "case_key", "TEXT")
        _ensure_column(conn, "evaluation_cases", "dataset_version", "TEXT NOT NULL DEFAULT 'custom'")
        _ensure_column(conn, "evaluation_cases", "category", "TEXT NOT NULL DEFAULT 'general'")
        _ensure_column(conn, "evaluation_cases", "should_answer", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "evaluation_cases", "updated_at", "TEXT")
        _ensure_column(conn, "batch_eval_runs", "dataset_version", "TEXT NOT NULL DEFAULT 'custom'")
        _ensure_column(conn, "batch_eval_runs", "dataset_hash", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "batch_eval_runs", "top_k", "INTEGER NOT NULL DEFAULT 5")
        _ensure_column(conn, "batch_eval_runs", "recall_at_k", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "batch_eval_runs", "mrr", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "batch_eval_runs", "answer_accuracy", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "batch_eval_runs", "abstention_accuracy", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "batch_eval_runs", "gate_status", "TEXT NOT NULL DEFAULT 'not_evaluated'")
        _ensure_column(conn, "batch_eval_runs", "thresholds_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "batch_eval_runs", "minimum_cases", "INTEGER NOT NULL DEFAULT 5")
        _ensure_column(conn, "batch_eval_runs", "max_regression", "REAL NOT NULL DEFAULT 0.05")
        _ensure_column(conn, "batch_eval_runs", "failed_metrics_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "batch_eval_runs", "metric_deltas_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "batch_eval_runs", "baseline_run_id", "INTEGER")
        _ensure_column(conn, "batch_eval_runs", "baseline_reference", "TEXT")
        _ensure_column(conn, "batch_eval_results", "should_answer", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "batch_eval_results", "retrieval_recall", "REAL")
        _ensure_column(conn, "batch_eval_results", "reciprocal_rank", "REAL")
        _ensure_column(conn, "batch_eval_results", "answer_correct", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "batch_eval_results", "abstention_correct", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "users", "is_active", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "knowledge_gaps", "assigned_to", "INTEGER")
        _ensure_column(conn, "knowledge_gaps", "resolution_action", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "knowledge_gaps", "before_score", "REAL")
        _ensure_column(conn, "knowledge_gaps", "after_score", "REAL")
        _ensure_column(conn, "knowledge_gaps", "review_answer", "TEXT")
        _ensure_column(conn, "knowledge_gaps", "review_citations_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "knowledge_gaps", "reviewed_by", "INTEGER")
        _ensure_column(conn, "knowledge_gaps", "reviewed_at", "TEXT")
        _ensure_column(conn, "agent_runs", "plan_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "agent_runs", "planner_mode", "TEXT NOT NULL DEFAULT 'deterministic'")
        _ensure_column(conn, "agent_runs", "error_message", "TEXT")
        _ensure_column(conn, "agent_runs", "started_at", "TEXT")
        _ensure_column(conn, "agent_runs", "completed_at", "TEXT")
        _ensure_column(conn, "agent_runs", "execution_mode", "TEXT NOT NULL DEFAULT 'sync'")
        _ensure_column(conn, "agent_runs", "top_k", "INTEGER NOT NULL DEFAULT 5")
        _ensure_column(conn, "agent_runs", "idempotency_key", "TEXT")
        _ensure_column(conn, "agent_runs", "parent_run_id", "INTEGER")
        _ensure_column(conn, "agent_runs", "cancel_requested_at", "TEXT")
        _ensure_column(conn, "agent_runs", "updated_at", "TEXT")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_runs_user_idempotency
            ON agent_runs(user_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_evaluation_cases_case_key
            ON evaluation_cases(case_key)
            WHERE case_key IS NOT NULL
            """
        )
        from .permissions import seed_default_permissions

        seed_default_permissions(conn)
        _seed_document_versions(conn)
        _seed_evaluation_cases(conn)

    from .auth import seed_default_users

    seed_default_users()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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
        placeholders = ",".join("?" for _ in candidates)
        existing = conn.execute(
            f"""
            SELECT id
            FROM evaluation_cases
            WHERE case_key = ? OR question IN ({placeholders})
            ORDER BY CASE WHEN case_key = ? THEN 0 WHEN question = ? THEN 1 ELSE 2 END, id
            LIMIT 1
            """,
            (case["key"], *candidates, case["key"], case["question"]),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE evaluation_cases
                SET case_key = ?, dataset_version = ?, category = ?, question = ?,
                    expected_keywords = ?, expected_documents = ?, should_answer = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    case["key"],
                    dataset["version"],
                    case["category"],
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
                case_key, dataset_version, category, question,
                expected_keywords, expected_documents, should_answer, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case["key"],
                dataset["version"],
                case["category"],
                case["question"],
                json.dumps(case["expected_keywords"], ensure_ascii=False),
                json.dumps(case["expected_documents"], ensure_ascii=False),
                1 if case["should_answer"] else 0,
                utc_now(),
                utc_now(),
            ),
        )
