from pathlib import Path

import pytest

from app import auth
from app.db import get_conn


ROOT = Path(__file__).resolve().parents[2]


def clear_users() -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM users")


def test_production_bootstrap_requires_a_strong_password_for_an_empty_database(monkeypatch):
    clear_users()
    monkeypatch.setattr(auth, "RUNTIME_ENV", "production")
    monkeypatch.setattr(auth, "BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setattr(auth, "BOOTSTRAP_ADMIN_PASSWORD", "")

    with pytest.raises(RuntimeError, match="RAG_BOOTSTRAP_ADMIN_PASSWORD"):
        auth.seed_default_users()

    monkeypatch.setattr(auth, "BOOTSTRAP_ADMIN_PASSWORD", "too-short")
    with pytest.raises(RuntimeError, match="at least 12"):
        auth.seed_default_users()


def test_production_bootstrap_creates_only_one_configured_admin(monkeypatch):
    clear_users()
    monkeypatch.setattr(auth, "RUNTIME_ENV", "production")
    monkeypatch.setattr(auth, "BOOTSTRAP_ADMIN_USERNAME", "platform-owner")
    monkeypatch.setattr(auth, "BOOTSTRAP_ADMIN_PASSWORD", "initial-admin-passphrase")

    auth.seed_default_users()

    with get_conn() as conn:
        users = conn.execute(
            "SELECT username, password_hash, role FROM users ORDER BY id"
        ).fetchall()
    assert [(row["username"], row["role"]) for row in users] == [("platform-owner", "admin")]
    assert auth.verify_password(users[0]["password_hash"], "initial-admin-passphrase")

    monkeypatch.setattr(auth, "BOOTSTRAP_ADMIN_PASSWORD", "replacement-passphrase")
    auth.seed_default_users()
    with get_conn() as conn:
        persisted = conn.execute(
            "SELECT password_hash FROM users WHERE username = 'platform-owner'"
        ).fetchone()
        assert conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"] == 1
    assert auth.verify_password(persisted["password_hash"], "initial-admin-passphrase")
    assert not auth.verify_password(persisted["password_hash"], "replacement-passphrase")


def test_runtime_requirements_are_a_locked_subset_of_test_requirements():
    runtime_path = ROOT / "backend" / "requirements-runtime.txt"
    runtime = {
        line.strip()
        for line in runtime_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    development = {
        line.strip()
        for line in (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert runtime
    assert runtime < development
    assert all("==" in requirement for requirement in runtime)


def test_container_delivery_has_hardened_runtime_contracts():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "requirements-runtime.txt" in dockerfile
    assert "USER rag" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "/api/health/ready" in dockerfile
    assert '"--workers", "1"' in dockerfile

    for contract in (
        "read_only: true",
        "no-new-privileges:true",
        "cap_drop:",
        "rag_data:/app/data",
        "RAG_RUNTIME_ENV: production",
        "${RAG_BOOTSTRAP_ADMIN_PASSWORD:?",
    ):
        assert contract in compose

    for excluded in (".env", ".git", ".runtime", "backups", "backend/data", "backend/tests"):
        assert excluded in dockerignore

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "backups/" in gitignore


def test_container_deployment_is_documented_and_ci_smoke_tested():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    deployment = (ROOT / "docs" / "container_deployment.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

    assert "docs/container_deployment.md" in readme
    assert "docker compose up --build -d" in deployment
    assert "RAG_BOOTSTRAP_ADMIN_PASSWORD" in deployment
    assert "SQLite" in deployment
    assert "container-smoke" in workflow
    assert "docker compose config --quiet" in workflow
    assert "docker build" in workflow
    assert "/api/health/ready" in workflow


def test_pgvector_profile_and_ci_use_a_real_extension_image():
    compose = (ROOT / "compose.pgvector.yaml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

    for contract in (
        "pgvector/pgvector:0.8.2-pg17-bookworm",
        "RAG_VECTOR_STORE: pgvector",
        "PGVECTOR_DSN:",
        "condition: service_healthy",
        "pgvector_data:/var/lib/postgresql/data",
    ):
        assert contract in compose
    assert "pgvector-integration:" in workflow
    assert "tests/test_pgvector_integration.py" in workflow
    assert "PGVECTOR_TEST_DSN" in workflow

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "pgvector_retrieval.md").read_text(encoding="utf-8")
    assert "docs/pgvector_retrieval.md" in readme
    for contract in (
        "compose.pgvector.yaml",
        "/api/documents/vector-store/sync",
        "RAG_VECTOR_STORE_FALLBACK",
        "SQLite 与 pgvector 无法共享事务",
        "PGVECTOR_DIMENSIONS",
    ):
        assert contract in guide
