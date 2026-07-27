import json

from app import qa
from app.db import get_conn, utc_now
from app.llm import LLMGeneration
from app.text_processing import token_counts


def seed_policy_document():
    content = "员工事假应至少提前一个工作日提交申请，由直属主管审批。"
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO documents(
                title, filename, file_type, storage_path, access_level,
                status, chunk_count, version, created_at
            )
            VALUES ('员工请假制度', 'leave.md', 'md', 'test', 'internal', 'ready', 1, 1, ?)
            """,
            (utc_now(),),
        )
        conn.execute(
            """
            INSERT INTO chunks(document_id, chunk_index, content, token_json, created_at)
            VALUES (?, 0, ?, ?, ?)
            """,
            (cursor.lastrowid, content, json.dumps(token_counts(content), ensure_ascii=False), utc_now()),
        )


def test_llm_provider_usage_is_exposed_in_observability(client, employee_headers, monkeypatch):
    seed_policy_document()
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setattr(
        qa,
        "generate_with_llm",
        lambda _question, _citations: LLMGeneration(
            answer="根据制度，员工事假应至少提前一个工作日申请。[1]",
            model="interview-test-model",
            attempted=True,
            usage={"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
            provider_attempts=2,
            provider_latency_ms=84,
            provider_status_code=200,
        ),
    )

    response = client.post(
        "/api/ask",
        headers=employee_headers,
        json={"question": "员工事假需要提前多久申请？"},
    )

    assert response.status_code == 200
    usage = response.json()["usage"]
    assert usage["generation_mode"] == "llm"
    assert usage["token_source"] == "provider"
    assert usage["model"] == "interview-test-model"
    assert usage["total_tokens"] == 150
    assert usage["provider_attempts"] == 2
    assert usage["provider_latency_ms"] == 84
    assert usage["provider_status_code"] == 200
    generation_step = response.json()["agent_trace"][-1]
    assert generation_step["metrics"]["generation_mode"] == "llm"
    with get_conn() as conn:
        persisted = json.loads(conn.execute("SELECT usage_json FROM qa_logs ORDER BY id DESC LIMIT 1").fetchone()[0])
    assert persisted["provider_attempts"] == 2
    assert persisted["provider_latency_ms"] == 84


def test_llm_failure_is_marked_as_local_fallback(client, employee_headers, monkeypatch):
    seed_policy_document()
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setattr(
        qa,
        "generate_with_llm",
        lambda _question, _citations: LLMGeneration(
            answer=None,
            model="interview-test-model",
            attempted=True,
            usage={},
            fallback_reason="provider_unavailable",
            provider_attempts=3,
            provider_latency_ms=250,
            provider_status_code=503,
        ),
    )

    response = client.post(
        "/api/ask",
        headers=employee_headers,
        json={"question": "员工事假需要提前多久申请？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "提前一个工作日" in body["answer"]
    assert body["usage"]["model"] == "local-extractive"
    assert body["usage"]["requested_model"] == "interview-test-model"
    assert body["usage"]["generation_mode"] == "local_fallback"
    assert body["usage"]["fallback_reason"] == "provider_unavailable"
    assert body["usage"]["provider_attempts"] == 3
    assert body["usage"]["provider_latency_ms"] == 250
    assert body["usage"]["provider_status_code"] == 503
    assert body["usage"]["token_source"] == "estimated"
