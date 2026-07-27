import io
import json
import socket
import urllib.error

import pytest

from app import agent_planner, embeddings, llm, provider_gateway
from app.provider_gateway import ProviderPolicy, ProviderResponse


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _size: int = -1) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


@pytest.fixture(autouse=True)
def reset_gateway():
    provider_gateway.reset_provider_gateway_state()
    yield
    provider_gateway.reset_provider_gateway_state()


def policy(max_attempts: int = 3) -> ProviderPolicy:
    return ProviderPolicy(
        timeout_seconds=1,
        max_attempts=max_attempts,
        retry_base_seconds=0.01,
        retry_max_seconds=1,
    )


def test_rate_limit_is_retried_and_retry_after_is_bounded(monkeypatch):
    calls = {"count": 0}
    sleeps = []

    def flaky_urlopen(_request, timeout):
        assert timeout == 1
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.HTTPError(
                "https://provider.example/v1/chat/completions",
                429,
                "rate limited",
                {"Retry-After": "0.75"},
                io.BytesIO(),
            )
        return FakeResponse({"ok": True})

    monkeypatch.setattr(provider_gateway.urllib.request, "urlopen", flaky_urlopen)
    monkeypatch.setattr(provider_gateway.time, "sleep", sleeps.append)

    result = provider_gateway.post_json(
        "https://provider.example/v1/chat/completions",
        payload={"model": "test"},
        headers={"Authorization": "Bearer test"},
        policy=policy(),
    )

    assert result.ready is True
    assert result.attempts == 2
    assert result.status_code == 200
    assert sleeps == [0.75]
    assert provider_gateway.provider_gateway_health()["retries"] == 1


def test_auth_failure_is_not_retried(monkeypatch):
    calls = {"count": 0}

    def rejected_urlopen(_request, timeout):
        calls["count"] += 1
        raise urllib.error.HTTPError(
            "https://provider.example/v1/chat/completions",
            401,
            "unauthorized",
            {},
            io.BytesIO(),
        )

    monkeypatch.setattr(provider_gateway.urllib.request, "urlopen", rejected_urlopen)

    result = provider_gateway.post_json(
        "https://provider.example/v1/chat/completions",
        payload={},
        headers={},
        policy=policy(),
    )

    assert result.error == "provider_auth_error"
    assert result.status_code == 401
    assert result.attempts == 1
    assert calls["count"] == 1


def test_timeout_is_retried_and_preserves_error_classification(monkeypatch):
    calls = {"count": 0}
    monkeypatch.setattr(provider_gateway.time, "sleep", lambda _delay: None)

    def timeout_urlopen(_request, timeout):
        calls["count"] += 1
        raise socket.timeout("provider did not respond")

    monkeypatch.setattr(provider_gateway.urllib.request, "urlopen", timeout_urlopen)

    result = provider_gateway.post_json(
        "https://provider.example/v1/embeddings",
        payload={},
        headers={},
        policy=policy(max_attempts=2),
    )

    assert result.error == "provider_timeout"
    assert result.attempts == 2
    assert calls["count"] == 2


def test_repeated_transient_failures_open_circuit(monkeypatch):
    calls = {"count": 0}
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("MODEL_GATEWAY_CIRCUIT_FAILURE_THRESHOLD", "2")
    monkeypatch.setenv("MODEL_GATEWAY_CIRCUIT_COOLDOWN_SECONDS", "60")

    def unavailable_urlopen(_request, timeout):
        calls["count"] += 1
        raise urllib.error.HTTPError(
            "https://provider.example/v1/chat/completions",
            503,
            "unavailable",
            {},
            io.BytesIO(),
        )

    monkeypatch.setattr(provider_gateway.urllib.request, "urlopen", unavailable_urlopen)

    first = provider_gateway.post_json(
        "https://provider.example/v1/chat/completions",
        payload={},
        headers={},
        policy=policy(max_attempts=1),
    )
    second = provider_gateway.post_json(
        "https://provider.example/v1/chat/completions",
        payload={},
        headers={},
        policy=policy(max_attempts=1),
    )
    rejected = provider_gateway.post_json(
        "https://provider.example/v1/embeddings",
        payload={},
        headers={},
        policy=policy(max_attempts=1),
    )

    assert first.error == second.error == "provider_unavailable"
    assert rejected.error == "provider_circuit_open"
    assert rejected.attempts == 0
    assert calls["count"] == 2
    health = provider_gateway.provider_gateway_health()
    assert health["status"] == "degraded"
    assert health["circuit_state"] == "open"
    assert health["circuit_rejections"] == 1
    assert "provider.example" not in json.dumps(health)


def test_half_open_circuit_closes_when_provider_returns_non_retryable_response(monkeypatch):
    monkeypatch.setenv("MODEL_GATEWAY_CIRCUIT_FAILURE_THRESHOLD", "1")
    responses = [503, 401]

    def sequenced_urlopen(_request, timeout):
        status = responses.pop(0)
        raise urllib.error.HTTPError(
            "https://provider.example/v1/chat/completions",
            status,
            "provider error",
            {},
            io.BytesIO(),
        )

    monkeypatch.setattr(provider_gateway.urllib.request, "urlopen", sequenced_urlopen)
    first = provider_gateway.post_json(
        "https://provider.example/v1/chat/completions",
        payload={},
        headers={},
        policy=policy(max_attempts=1),
    )
    assert first.error == "provider_unavailable"
    circuit = next(iter(provider_gateway._circuits.values()))
    circuit.open_until = provider_gateway.time.monotonic() - 1

    probe = provider_gateway.post_json(
        "https://provider.example/v1/chat/completions",
        payload={},
        headers={},
        policy=policy(max_attempts=1),
    )

    assert probe.error == "provider_auth_error"
    assert provider_gateway.provider_gateway_health()["circuit_state"] == "closed"


def test_policy_and_response_size_are_bounded(monkeypatch):
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "999")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "9999")
    bounded = provider_gateway.policy_from_env(
        "LLM",
        default_timeout_seconds=20,
        default_max_attempts=3,
    )
    assert bounded.max_attempts == 10
    assert bounded.timeout_seconds == 300

    monkeypatch.setenv("MODEL_GATEWAY_MAX_RESPONSE_BYTES", "1024")
    monkeypatch.setattr(
        provider_gateway.urllib.request,
        "urlopen",
        lambda _request, timeout: FakeResponse({"content": "x" * 2048}),
    )
    result = provider_gateway.post_json(
        "https://provider.example/v1/chat/completions",
        payload={},
        headers={},
        policy=policy(max_attempts=1),
    )
    assert result.error == "invalid_provider_response"
    assert result.attempts == 1


def test_llm_generation_exposes_gateway_diagnostics(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setattr(
        llm,
        "post_json",
        lambda *_args, **_kwargs: ProviderResponse(
            payload={
                "choices": [{"message": {"content": "Grounded answer [1]"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            },
            error=None,
            attempts=2,
            latency_ms=83,
            status_code=200,
        ),
    )

    result = llm.generate_with_llm(
        "question",
        [{"document_title": "Policy", "chunk_index": 0, "content": "Approved evidence"}],
    )

    assert result.answer == "Grounded answer [1]"
    assert result.provider_attempts == 2
    assert result.provider_latency_ms == 83
    assert result.provider_status_code == 200

    monkeypatch.setattr(
        llm,
        "post_json",
        lambda *_args, **_kwargs: ProviderResponse(
            payload={"choices": [{"message": {"content": None}}]},
            error=None,
            attempts=1,
            latency_ms=10,
            status_code=200,
        ),
    )
    malformed = llm.generate_with_llm(
        "question",
        [{"document_title": "Policy", "chunk_index": 0, "content": "Approved evidence"}],
    )
    assert malformed.fallback_reason == "invalid_provider_response"


def test_embedding_batch_exposes_gateway_diagnostics(monkeypatch):
    monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("EMBEDDING_MODEL", "test-embedding")
    monkeypatch.setattr(
        embeddings,
        "post_json",
        lambda *_args, **_kwargs: ProviderResponse(
            payload={"data": [{"index": 0, "embedding": [0.2, 0.8]}]},
            error=None,
            attempts=2,
            latency_ms=41,
            status_code=200,
        ),
    )

    result = embeddings.embed_texts(["policy text"])

    assert result.status == "ready"
    assert result.vectors == [[0.2, 0.8]]
    assert result.provider_attempts == 2
    assert result.provider_latency_ms == 41

    monkeypatch.setattr(
        embeddings,
        "post_json",
        lambda *_args, **_kwargs: ProviderResponse(
            payload={"data": {}},
            error=None,
            attempts=1,
            latency_ms=8,
            status_code=200,
        ),
    )
    malformed = embeddings.embed_texts(["policy text"])
    assert malformed.status == "failed"
    assert malformed.error == "invalid_provider_response"


def test_agent_planner_exposes_gateway_diagnostics(monkeypatch):
    monkeypatch.setenv("AGENT_PLANNER_ENABLED", "true")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setattr(
        agent_planner,
        "post_json",
        lambda *_args, **_kwargs: ProviderResponse(
            payload={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "tools": [
                                        "security_check",
                                        "search_knowledge_base",
                                        "generate_grounded_answer",
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
            error=None,
            attempts=2,
            latency_ms=57,
            status_code=200,
        ),
    )

    result = agent_planner.plan_agent("find the leave policy", can_manage_gaps=False, can_view_audit=False)

    assert result.mode == "llm"
    assert result.provider_attempts == 2
    assert result.provider_latency_ms == 57
    assert result.provider_status_code == 200
