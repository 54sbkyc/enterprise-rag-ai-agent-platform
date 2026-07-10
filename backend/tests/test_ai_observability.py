import json

from app.db import get_conn, utc_now
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
            (
                cursor.lastrowid,
                content,
                json.dumps(token_counts(content), ensure_ascii=False),
                utc_now(),
            ),
        )


def test_ask_returns_and_persists_agent_trace_and_usage(client, employee_headers):
    seed_policy_document()

    response = client.post(
        "/api/ask",
        headers=employee_headers,
        json={"question": "员工事假需要提前多久申请？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [step["stage"] for step in body["agent_trace"]] == [
        "security_check",
        "permission_scope",
        "retrieval",
        "answer_generation",
    ]
    assert body["agent_trace"][2]["metrics"]["hit_count"] >= 1
    assert body["usage"]["model"] == "local-extractive"
    assert body["usage"]["total_tokens"] > 0
    assert body["usage"]["estimated_cost_usd"] == 0

    with get_conn() as conn:
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(qa_logs)").fetchall()]
        assert "agent_trace_json" in columns
        assert "usage_json" in columns
        row = conn.execute(
            "SELECT agent_trace_json, usage_json FROM qa_logs WHERE id = ?",
            (body["log_id"],),
        ).fetchone()

    persisted_trace = json.loads(row["agent_trace_json"])
    persisted_usage = json.loads(row["usage_json"])
    assert persisted_trace[0]["stage"] == "security_check"
    assert persisted_usage["total_tokens"] == body["usage"]["total_tokens"]


def test_stats_summarize_ai_usage(client, employee_headers, admin_headers):
    seed_policy_document()
    ask_response = client.post(
        "/api/ask",
        headers=employee_headers,
        json={"question": "员工事假需要提前多久申请？"},
    )
    assert ask_response.status_code == 200

    stats_response = client.get("/api/stats", headers=admin_headers)

    assert stats_response.status_code == 200
    usage = stats_response.json()["ai_usage"]
    assert usage["request_count"] == 1
    assert usage["total_tokens"] >= ask_response.json()["usage"]["total_tokens"]
    assert usage["estimated_cost_usd"] >= 0
