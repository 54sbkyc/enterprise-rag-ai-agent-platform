import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence


MIGRATION_TABLE = "schema_migrations"
MIGRATION_DIR = Path(__file__).with_name("migrations")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ColumnAddition:
    table: str
    column: str
    definition: str


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    filename: str
    columns: tuple[ColumnAddition, ...] = ()
    statements: tuple[str, ...] = ()


@dataclass(frozen=True)
class MigrationStatus:
    status: str
    current_version: int
    expected_version: int
    applied_count: int
    pending_versions: tuple[int, ...] = ()
    issues: tuple[str, ...] = ()
    last_applied_at: str | None = None
    history: tuple[dict, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def public_dict(self, *, include_history: bool = False) -> dict:
        result = {
            "status": self.status,
            "current_version": self.current_version,
            "expected_version": self.expected_version,
            "applied_count": self.applied_count,
            "pending_versions": list(self.pending_versions),
        }
        if self.issues:
            result["issues"] = list(self.issues)
        if self.last_applied_at:
            result["last_applied_at"] = self.last_applied_at
        if include_history:
            result["history"] = list(self.history)
        return result


class MigrationError(RuntimeError):
    pass


class MigrationDriftError(MigrationError):
    pass


LEGACY_COLUMNS = (
    ColumnAddition("documents", "access_level", "TEXT NOT NULL DEFAULT 'internal'"),
    ColumnAddition("documents", "version", "INTEGER NOT NULL DEFAULT 1"),
    ColumnAddition("documents", "embedding_status", "TEXT NOT NULL DEFAULT 'not_configured'"),
    ColumnAddition("documents", "embedding_model", "TEXT"),
    ColumnAddition("chunks", "embedding_json", "TEXT NOT NULL DEFAULT '[]'"),
    ColumnAddition("chunks", "embedding_model", "TEXT"),
    ColumnAddition("chunks", "content_hash", "TEXT NOT NULL DEFAULT ''"),
    ColumnAddition("qa_logs", "user_id", "INTEGER"),
    ColumnAddition("qa_logs", "agent_trace_json", "TEXT NOT NULL DEFAULT '[]'"),
    ColumnAddition("qa_logs", "usage_json", "TEXT NOT NULL DEFAULT '{}'"),
    ColumnAddition("evaluations", "user_id", "INTEGER"),
    ColumnAddition("evaluations", "expected_documents", "TEXT NOT NULL DEFAULT '[]'"),
    ColumnAddition("evaluations", "citation_hit", "REAL NOT NULL DEFAULT 0"),
    ColumnAddition("evaluation_cases", "case_key", "TEXT"),
    ColumnAddition("evaluation_cases", "dataset_version", "TEXT NOT NULL DEFAULT 'custom'"),
    ColumnAddition("evaluation_cases", "category", "TEXT NOT NULL DEFAULT 'general'"),
    ColumnAddition("evaluation_cases", "actor_role", "TEXT NOT NULL DEFAULT 'admin'"),
    ColumnAddition("evaluation_cases", "should_answer", "INTEGER NOT NULL DEFAULT 1"),
    ColumnAddition("evaluation_cases", "updated_at", "TEXT"),
    ColumnAddition("batch_eval_runs", "dataset_version", "TEXT NOT NULL DEFAULT 'custom'"),
    ColumnAddition("batch_eval_runs", "dataset_hash", "TEXT NOT NULL DEFAULT ''"),
    ColumnAddition("batch_eval_runs", "top_k", "INTEGER NOT NULL DEFAULT 5"),
    ColumnAddition("batch_eval_runs", "recall_at_k", "REAL NOT NULL DEFAULT 0"),
    ColumnAddition("batch_eval_runs", "mrr", "REAL NOT NULL DEFAULT 0"),
    ColumnAddition("batch_eval_runs", "answer_accuracy", "REAL NOT NULL DEFAULT 0"),
    ColumnAddition("batch_eval_runs", "abstention_accuracy", "REAL NOT NULL DEFAULT 0"),
    ColumnAddition("batch_eval_runs", "access_control_accuracy", "REAL NOT NULL DEFAULT 0"),
    ColumnAddition("batch_eval_runs", "gate_status", "TEXT NOT NULL DEFAULT 'not_evaluated'"),
    ColumnAddition("batch_eval_runs", "thresholds_json", "TEXT NOT NULL DEFAULT '{}'"),
    ColumnAddition("batch_eval_runs", "minimum_cases", "INTEGER NOT NULL DEFAULT 10"),
    ColumnAddition("batch_eval_runs", "max_regression", "REAL NOT NULL DEFAULT 0.05"),
    ColumnAddition("batch_eval_runs", "failed_metrics_json", "TEXT NOT NULL DEFAULT '[]'"),
    ColumnAddition("batch_eval_runs", "metric_deltas_json", "TEXT NOT NULL DEFAULT '{}'"),
    ColumnAddition("batch_eval_runs", "baseline_run_id", "INTEGER"),
    ColumnAddition("batch_eval_runs", "baseline_reference", "TEXT"),
    ColumnAddition("batch_eval_results", "should_answer", "INTEGER NOT NULL DEFAULT 1"),
    ColumnAddition("batch_eval_results", "actor_role", "TEXT NOT NULL DEFAULT 'admin'"),
    ColumnAddition("batch_eval_results", "retrieval_recall", "REAL"),
    ColumnAddition("batch_eval_results", "reciprocal_rank", "REAL"),
    ColumnAddition("batch_eval_results", "answer_correct", "INTEGER NOT NULL DEFAULT 0"),
    ColumnAddition("batch_eval_results", "abstention_correct", "INTEGER NOT NULL DEFAULT 0"),
    ColumnAddition("batch_eval_results", "access_control_correct", "INTEGER NOT NULL DEFAULT 0"),
    ColumnAddition("users", "is_active", "INTEGER NOT NULL DEFAULT 1"),
    ColumnAddition("knowledge_gaps", "assigned_to", "INTEGER"),
    ColumnAddition("knowledge_gaps", "resolution_action", "TEXT NOT NULL DEFAULT ''"),
    ColumnAddition("knowledge_gaps", "before_score", "REAL"),
    ColumnAddition("knowledge_gaps", "after_score", "REAL"),
    ColumnAddition("knowledge_gaps", "review_answer", "TEXT"),
    ColumnAddition("knowledge_gaps", "review_citations_json", "TEXT NOT NULL DEFAULT '[]'"),
    ColumnAddition("knowledge_gaps", "reviewed_by", "INTEGER"),
    ColumnAddition("knowledge_gaps", "reviewed_at", "TEXT"),
    ColumnAddition("agent_runs", "plan_json", "TEXT NOT NULL DEFAULT '{}'"),
    ColumnAddition("agent_runs", "planner_mode", "TEXT NOT NULL DEFAULT 'deterministic'"),
    ColumnAddition("agent_runs", "error_message", "TEXT"),
    ColumnAddition("agent_runs", "started_at", "TEXT"),
    ColumnAddition("agent_runs", "completed_at", "TEXT"),
    ColumnAddition("agent_runs", "execution_mode", "TEXT NOT NULL DEFAULT 'sync'"),
    ColumnAddition("agent_runs", "top_k", "INTEGER NOT NULL DEFAULT 5"),
    ColumnAddition("agent_runs", "idempotency_key", "TEXT"),
    ColumnAddition("agent_runs", "parent_run_id", "INTEGER"),
    ColumnAddition("agent_runs", "cancel_requested_at", "TEXT"),
    ColumnAddition("agent_runs", "updated_at", "TEXT"),
)

BASELINE_INDEXES = (
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_runs_user_idempotency
    ON agent_runs(user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_evaluation_cases_case_key
    ON evaluation_cases(case_key)
    WHERE case_key IS NOT NULL
    """,
    "CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_embedding_model ON chunks(embedding_model)",
    "CREATE INDEX IF NOT EXISTS idx_documents_access_status ON documents(access_level, status)",
)

MIGRATIONS = (
    Migration(
        version=1,
        name="legacy_schema_baseline",
        filename="0001_legacy_baseline.sql",
        columns=LEGACY_COLUMNS,
        statements=BASELINE_INDEXES,
    ),
)
LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version
SqlLoader = Callable[[Migration], str]


def apply_migrations(
    conn: sqlite3.Connection,
    migrations: Sequence[Migration] = MIGRATIONS,
    sql_loader: SqlLoader | None = None,
) -> MigrationStatus:
    registry = _validated_registry(migrations)
    loader = sql_loader or _load_sql
    if conn.in_transaction:
        raise MigrationError("migrations must start outside an active transaction")
    _ensure_history_table(conn)

    try:
        initial = migration_status(conn, registry, loader)
    except sqlite3.Error as exc:
        raise MigrationError("cannot read database migration history") from exc
    if initial.status == "drift_detected":
        raise MigrationDriftError("applied database migration differs from repository history")
    if initial.status == "unsupported":
        raise MigrationError("database contains a migration newer than this application")

    for migration in registry:
        conn.execute("BEGIN IMMEDIATE")
        try:
            applied = conn.execute(
                f"SELECT name, checksum FROM {MIGRATION_TABLE} WHERE version = ?",
                (migration.version,),
            ).fetchone()
            sql = loader(migration)
            checksum = migration_checksum(migration, sql)
            if applied:
                if applied[0] != migration.name or applied[1] != checksum:
                    raise MigrationDriftError(
                        f"migration {migration.version} history does not match repository"
                    )
                conn.commit()
                continue

            started = time.monotonic()
            _apply_migration(conn, migration, sql)
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise MigrationError(
                    f"migration {migration.version} produced foreign key violations"
                )
            duration_ms = max(0, round((time.monotonic() - started) * 1000))
            conn.execute(
                f"""
                INSERT INTO {MIGRATION_TABLE}(version, name, checksum, applied_at, duration_ms)
                VALUES (?, ?, ?, ?, ?)
                """,
                (migration.version, migration.name, checksum, _utc_now(), duration_ms),
            )
            conn.commit()
        except MigrationError:
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise MigrationError(f"migration {migration.version} failed: {exc}") from exc

    result = migration_status(conn, registry, loader)
    if not result.ready:
        raise MigrationError(f"schema migration did not become ready: {result.status}")
    return result


def migration_status(
    conn: sqlite3.Connection,
    migrations: Sequence[Migration] = MIGRATIONS,
    sql_loader: SqlLoader | None = None,
) -> MigrationStatus:
    registry = _validated_registry(migrations)
    loader = sql_loader or _load_sql
    expected_version = registry[-1].version if registry else 0
    if not _table_exists(conn, MIGRATION_TABLE):
        return MigrationStatus(
            status="uninitialized",
            current_version=0,
            expected_version=expected_version,
            applied_count=0,
            pending_versions=tuple(item.version for item in registry),
        )

    rows = conn.execute(
        f"""
        SELECT version, name, checksum, applied_at, duration_ms
        FROM {MIGRATION_TABLE}
        ORDER BY version
        """
    ).fetchall()
    expected = {item.version: item for item in registry}
    applied_versions = {int(row[0]) for row in rows}
    issues: list[str] = []
    has_unknown = False
    has_drift = False
    history: list[dict] = []

    for row in rows:
        version = int(row[0])
        migration = expected.get(version)
        item_status = "applied"
        if migration is None:
            has_unknown = True
            item_status = "unknown"
            issues.append(f"unknown_migration:{version}")
        else:
            checksum = migration_checksum(migration, loader(migration))
            if row[1] != migration.name:
                has_drift = True
                item_status = "drifted"
                issues.append(f"name_mismatch:{version}")
            if row[2] != checksum:
                has_drift = True
                item_status = "drifted"
                issues.append(f"checksum_mismatch:{version}")
        history.append(
            {
                "version": version,
                "name": row[1],
                "checksum": row[2],
                "applied_at": row[3],
                "duration_ms": int(row[4]),
                "status": item_status,
            }
        )

    pending = tuple(item.version for item in registry if item.version not in applied_versions)
    if has_drift:
        status = "drift_detected"
    elif has_unknown:
        status = "unsupported"
    elif pending:
        status = "pending"
    else:
        status = "ready"
    return MigrationStatus(
        status=status,
        current_version=max(applied_versions, default=0),
        expected_version=expected_version,
        applied_count=len(rows),
        pending_versions=pending,
        issues=tuple(issues),
        last_applied_at=rows[-1][3] if rows else None,
        history=tuple(history),
    )


def migration_checksum(migration: Migration, sql: str) -> str:
    metadata = {
        "version": migration.version,
        "name": migration.name,
        "filename": migration.filename,
        "columns": [
            [item.table, item.column, item.definition] for item in migration.columns
        ],
        "statements": list(migration.statements),
    }
    digest = hashlib.sha256()
    digest.update(sql.encode("utf-8"))
    digest.update(b"\0")
    digest.update(
        json.dumps(metadata, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return digest.hexdigest()


def _apply_migration(conn: sqlite3.Connection, migration: Migration, sql: str) -> None:
    for statement in _iter_sql_statements(sql):
        conn.execute(statement)
    for addition in migration.columns:
        _ensure_column(conn, addition)
    for statement in migration.statements:
        conn.execute(statement)


def _ensure_history_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            duration_ms INTEGER NOT NULL CHECK(duration_ms >= 0)
        )
        """
    )
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, addition: ColumnAddition) -> None:
    table = _safe_identifier(addition.table)
    column = _safe_identifier(addition.column)
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if not columns:
        raise MigrationError(f"migration target table does not exist: {table}")
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {addition.definition}")


def _iter_sql_statements(sql: str) -> Iterable[str]:
    buffer: list[str] = []
    for line in sql.splitlines(keepends=True):
        buffer.append(line)
        candidate = "".join(buffer).strip()
        if candidate and sqlite3.complete_statement(candidate):
            yield candidate
            buffer.clear()
    if "".join(buffer).strip():
        raise MigrationError("migration SQL ends with an incomplete statement")


def _validated_registry(migrations: Sequence[Migration]) -> tuple[Migration, ...]:
    registry = tuple(migrations)
    versions = [item.version for item in registry]
    if versions != list(range(1, len(registry) + 1)):
        raise MigrationError("migration versions must be unique, ordered, and contiguous from 1")
    if any(not item.name.strip() or not item.filename.strip() for item in registry):
        raise MigrationError("migration name and filename are required")
    return registry


def _load_sql(migration: Migration) -> str:
    path = (MIGRATION_DIR / migration.filename).resolve()
    if path.parent != MIGRATION_DIR.resolve():
        raise MigrationError("migration file must stay inside the migration directory")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MigrationError(f"cannot read migration file: {migration.filename}") from exc


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _safe_identifier(value: str) -> str:
    if not _IDENTIFIER_PATTERN.fullmatch(value):
        raise MigrationError(f"unsafe migration identifier: {value!r}")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
