import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.migration_cli import main as migration_cli_main
from app.migrations import (
    MIGRATION_DIR,
    MIGRATIONS,
    Migration,
    MigrationDriftError,
    MigrationError,
    apply_migrations,
    migration_status,
)


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def load_test_sql(migration: Migration) -> str:
    if migration.version == 1:
        return (MIGRATION_DIR / migration.filename).read_text(encoding="utf-8")
    return """
    CREATE TABLE rollback_probe(id INTEGER PRIMARY KEY);
    INSERT INTO rollback_probe(id) VALUES (1);
    THIS IS NOT VALID SQL;
    """


def test_fresh_database_reaches_versioned_schema():
    with connect() as conn:
        status = apply_migrations(conn)

        assert status.ready is True
        assert status.current_version == status.expected_version == 2
        assert status.applied_count == 2
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'agent_runs'"
        ).fetchone()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
        assert {"access_level", "version", "embedding_status"} <= columns
        evaluation_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(batch_eval_results)")
        }
        assert {
            "citation_faithfulness",
            "safety_assertion_correct",
            "prompt_version",
            "total_tokens",
            "latency_ms",
        } <= evaluation_columns
        checksum = conn.execute("SELECT checksum FROM schema_migrations").fetchone()[0]
        assert len(checksum) == 64


def test_legacy_database_is_upgraded_without_losing_rows():
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ready',
                chunk_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            INSERT INTO documents(title, filename, file_type, storage_path, created_at)
            VALUES ('Legacy handbook', 'legacy.md', '.md', 'uploads/legacy.md', '2026-01-01T00:00:00Z');
            """
        )

        first = apply_migrations(conn)
        second = apply_migrations(conn)

        row = conn.execute(
            "SELECT title, access_level, version, embedding_status FROM documents WHERE id = 1"
        ).fetchone()
        assert row == ("Legacy handbook", "internal", 1, "not_configured")
        assert first.ready is True
        assert second.ready is True
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2


def test_checksum_drift_is_reported_and_blocks_startup():
    with connect() as conn:
        apply_migrations(conn, migrations=(MIGRATIONS[0],))
        conn.execute(
            "UPDATE schema_migrations SET checksum = ? WHERE version = 1",
            ("0" * 64,),
        )
        conn.commit()

        status = migration_status(conn)

        assert status.status == "drift_detected"
        assert status.issues == ("checksum_mismatch:1",)
        with pytest.raises(MigrationDriftError, match="differs from repository history"):
            apply_migrations(conn)


def test_failed_migration_rolls_back_schema_data_and_history():
    with connect() as conn:
        apply_migrations(conn, migrations=(MIGRATIONS[0],))
        migrations = (
            MIGRATIONS[0],
            Migration(version=2, name="failing_probe", filename="0002_failing_probe.sql"),
        )

        with pytest.raises(MigrationError, match="migration 2 failed"):
            apply_migrations(conn, migrations=migrations, sql_loader=load_test_sql)

        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rollback_probe'"
        ).fetchone() is None
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1


def test_unknown_newer_migration_is_rejected():
    with connect() as conn:
        apply_migrations(conn)
        conn.execute(
            """
            INSERT INTO schema_migrations(version, name, checksum, applied_at, duration_ms)
            VALUES (99, 'future', ?, '2026-01-01T00:00:00Z', 1)
            """,
            ("f" * 64,),
        )
        conn.commit()

        status = migration_status(conn)

        assert status.status == "unsupported"
        assert status.issues == ("unknown_migration:99",)
        with pytest.raises(MigrationError, match="newer than this application"):
            apply_migrations(conn)


def test_concurrent_upgrades_apply_each_version_once(tmp_path):
    database = str(tmp_path / "concurrent.db")

    def upgrade() -> str:
        with connect(database) as conn:
            return apply_migrations(conn).status

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: upgrade(), range(2)))

    with connect(database) as conn:
        assert results == ["ready", "ready"]
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2


def test_migration_cli_reports_machine_readable_history(capsys):
    exit_code = migration_cli_main(["status", "--compact"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ready"
    assert payload["current_version"] == payload["expected_version"] == 2
    assert payload["history"][0]["name"] == "legacy_schema_baseline"


def test_migration_cli_creates_integrity_checked_online_backup(tmp_path, capsys):
    destination = tmp_path / "before-upgrade.db"

    exit_code = migration_cli_main(
        ["backup", "--output", str(destination), "--compact"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "backup_created"
    assert payload["integrity_check"] == "ok"
    with connect(str(destination)) as backup:
        assert backup.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2
