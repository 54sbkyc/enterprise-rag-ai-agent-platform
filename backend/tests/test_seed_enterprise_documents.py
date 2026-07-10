import os
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_seed_enterprise_documents_bootstraps_clean_database(tmp_path):
    database = tmp_path / "rag.db"
    uploads = tmp_path / "uploads"
    env = os.environ.copy()
    env["RAG_DB_PATH"] = str(database)
    env["RAG_UPLOAD_DIR"] = str(uploads)

    result = subprocess.run(
        [sys.executable, "backend/seed_enterprise_documents.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"created_count" in result.stdout
    with sqlite3.connect(database) as conn:
        document_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    assert document_count > 0
    assert chunk_count > 0
