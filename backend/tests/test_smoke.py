def test_health_endpoint_uses_test_app(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_liveness_and_database_readiness_endpoints(client):
    live_response = client.get("/api/health/live")
    ready_response = client.get("/api/health/ready")

    assert live_response.status_code == 200
    assert live_response.json()["status"] == "alive"
    assert ready_response.status_code == 200
    assert ready_response.json()["status"] == "ready"
    assert ready_response.json()["database"] == "ok"
    schema = ready_response.json()["schema_migrations"]
    assert schema["status"] == "ready"
    assert schema["current_version"] == schema["expected_version"] == 2
    assert schema["pending_versions"] == []
    assert ready_response.json()["lexical_index"] == {
        "backend": "sqlite_fts5",
        "status": "ready",
    }
    assert ready_response.json()["vector_store"] == {
        "backend": "sqlite",
        "status": "ready",
        "count": 0,
    }
    model_gateway = ready_response.json()["model_gateway"]
    assert model_gateway["circuit_state"] == "closed"
    assert model_gateway["open_circuits"] == 0
    assert "requests" in model_gateway
    assert "attempts" in model_gateway


def test_readiness_returns_503_without_exposing_database_errors(client, monkeypatch):
    from app import main

    class BrokenConnection:
        def __enter__(self):
            raise OSError("private database path and failure details")

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(main, "get_conn", BrokenConnection)

    response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "service is not ready"}
    assert "private database path" not in response.text


def test_readiness_rejects_schema_version_mismatch(client, monkeypatch):
    from app import main
    from app.migrations import MigrationStatus

    monkeypatch.setattr(
        main,
        "migration_status",
        lambda _conn: MigrationStatus(
            status="pending",
            current_version=0,
            expected_version=1,
            applied_count=0,
            pending_versions=(1,),
        ),
    )

    response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "service is not ready"}


def test_readiness_exposes_pgvector_degradation_and_can_require_it(client, monkeypatch):
    from app import main
    from app.vector_store import VectorStoreResult

    monkeypatch.setattr(
        main,
        "vector_store_health",
        lambda: VectorStoreResult(
            backend="pgvector",
            status="degraded",
            error="pgvector_unavailable",
        ),
    )
    monkeypatch.setattr(main, "vector_store_fallback_enabled", lambda: True)
    degraded = client.get("/api/health/ready")
    assert degraded.status_code == 200
    assert degraded.json()["vector_store"]["status"] == "degraded"
    assert degraded.json()["vector_store"]["error"] == "pgvector_unavailable"

    monkeypatch.setattr(main, "vector_store_fallback_enabled", lambda: False)
    required = client.get("/api/health/ready")
    assert required.status_code == 503
    assert required.json() == {"detail": "service is not ready"}


def test_readiness_exposes_lexical_index_degradation(client, monkeypatch):
    from app import main
    from app.lexical_index import LexicalSearchResult

    monkeypatch.setattr(
        main,
        "lexical_index_health",
        lambda _conn: LexicalSearchResult(
            backend="full_scan",
            status="degraded",
            error="fts5_unavailable",
        ),
    )

    response = client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json()["lexical_index"] == {
        "backend": "full_scan",
        "status": "degraded",
        "error": "fts5_unavailable",
    }
