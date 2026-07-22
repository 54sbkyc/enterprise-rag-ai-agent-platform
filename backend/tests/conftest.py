import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_ROOT = Path(tempfile.mkdtemp(prefix="enterprise-rag-tests-"))
os.environ["RAG_DB_PATH"] = str(TEST_ROOT / "test.db")
os.environ["RAG_UPLOAD_DIR"] = str(TEST_ROOT / "uploads")
os.environ["RAG_RUNTIME_ENV"] = "test"

from app.auth import hash_password  # noqa: E402
from app.db import get_conn, init_db, utc_now  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def reset_database():
    database = Path(os.environ["RAG_DB_PATH"])
    database.unlink(missing_ok=True)
    shutil.rmtree(os.environ["RAG_UPLOAD_DIR"], ignore_errors=True)
    Path(os.environ["RAG_UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
    init_db()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users(username, password_hash, role, display_name, is_active, created_at)
            VALUES (?, ?, 'tech', '技术员工', 1, ?)
            """,
            ("tech", hash_password("tech123"), utc_now()),
        )
    yield


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def login_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.fixture()
def admin_headers(client):
    return login_headers(client, "admin", "admin123")


@pytest.fixture()
def tech_headers(client):
    return login_headers(client, "tech", "tech123")


@pytest.fixture()
def employee_headers(client):
    return login_headers(client, "employee", "user123")
