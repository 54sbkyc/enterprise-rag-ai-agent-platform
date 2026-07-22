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
