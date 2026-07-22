from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import main
from app.config import (
    APP_VERSION,
    MAX_UPLOAD_BYTES,
    SESSION_TTL_HOURS,
    parse_cors_origins,
    parse_runtime_environment,
)
from app.db import get_conn


def test_release_version_and_secure_runtime_defaults():
    assert APP_VERSION == "1.2.0"
    assert MAX_UPLOAD_BYTES == 10 * 1024 * 1024
    assert SESSION_TTL_HOURS == 12
    assert parse_cors_origins("") == ()
    assert parse_cors_origins("http://127.0.0.1:3000, https://app.example.com") == (
        "http://127.0.0.1:3000",
        "https://app.example.com",
    )
    with pytest.raises(ValueError, match="wildcard"):
        parse_cors_origins("*")
    assert parse_runtime_environment("") == "development"
    assert parse_runtime_environment(" PRODUCTION ") == "production"
    with pytest.raises(ValueError, match="RAG_RUNTIME_ENV"):
        parse_runtime_environment("staging-ish")


def test_expired_session_is_rejected_and_removed(client, admin_headers):
    token = admin_headers["Authorization"].split(" ", 1)[1]
    expired_at = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET created_at = ? WHERE token = ?", (expired_at, token))

    response = client.get("/api/auth/me", headers=admin_headers)

    assert response.status_code == 401
    assert response.json()["detail"] == "登录已过期，请重新登录"
    with get_conn() as conn:
        assert conn.execute("SELECT 1 FROM sessions WHERE token = ?", (token,)).fetchone() is None


def test_oversized_upload_is_rejected_without_leaving_files(client, admin_headers, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 32)

    response = client.post(
        "/api/documents/upload",
        headers=admin_headers,
        data={"access_level": "internal"},
        files={"file": ("large.md", b"x" * 64, "text/markdown")},
    )

    assert response.status_code == 413
    assert "文件大小不能超过" in response.json()["detail"]
    assert list(Path(main.UPLOAD_DIR).iterdir()) == []
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"] == 0
