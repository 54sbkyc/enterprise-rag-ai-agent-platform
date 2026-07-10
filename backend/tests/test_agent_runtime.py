import json

from app import agent, main
from app.agent_planner import deterministic_plan, validate_tool_steps
from app.db import get_conn, utc_now
from app.text_processing import token_counts


def seed_policy_document():
    content = "员工事假应至少提前一个工作日提交申请，由直属主管审批。"
    with get_conn() as conn:
        document_id = conn.execute(
            """
            INSERT INTO documents(
                title, filename, file_type, storage_path, access_level,
                status, chunk_count, version, created_at
            )
            VALUES ('员工请假制度', 'leave.md', 'md', 'test', 'internal', 'ready', 1, 1, ?)
            """,
            (utc_now(),),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO chunks(document_id, chunk_index, content, token_json, created_at)
            VALUES (?, 0, ?, ?, ?)
            """,
            (document_id, content, json.dumps(token_counts(content), ensure_ascii=False), utc_now()),
        )


def test_planner_rejects_unknown_or_out_of_order_tools():
    fallback = deterministic_plan("员工事假需要提前多久申请？")

    validated, reason = validate_tool_steps(
        ["delete_database", "generate_grounded_answer"],
        fallback.steps,
        can_manage_gaps=False,
        can_view_audit=False,
    )

    assert validated == fallback.steps
    assert reason == "invalid_tool_plan"


def test_agent_retries_transient_tool_failure_and_reports_plan(monkeypatch):
    seed_policy_document()
    original_search = agent.search_chunks
    attempts = {"count": 0}

    def flaky_search(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary search failure")
        return original_search(*args, **kwargs)

    monkeypatch.setattr(agent, "search_chunks", flaky_search)
    monkeypatch.setattr(agent, "AGENT_TOOL_MAX_ATTEMPTS", 2)

    result = agent.run_agent(
        "员工事假需要提前多久申请？",
        5,
        {"id": 2, "role": "employee", "username": "employee", "display_name": "普通员工"},
    )

    assert result["status"] == "completed"
    assert result["plan"]["mode"] == "deterministic"
    assert result["plan"]["steps"][:3] == [
        "security_check",
        "search_knowledge_base",
        "generate_grounded_answer",
    ]
    search_call = next(call for call in result["tool_calls"] if call["tool_name"] == "search_knowledge_base")
    assert search_call["attempts"] == 2
    assert search_call["duration_ms"] >= 0


def test_agent_api_persists_running_lifecycle_and_plan(client, employee_headers):
    seed_policy_document()

    response = client.post(
        "/api/agent/run",
        headers=employee_headers,
        json={"goal": "员工事假需要提前多久申请？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] > 0
    assert body["plan"]["steps"]
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT status, planner_mode, plan_json, started_at, completed_at, error_message
            FROM agent_runs WHERE id = ?
            """,
            (body["run_id"],),
        ).fetchone()
    assert row["status"] == "completed"
    assert row["planner_mode"] == body["plan"]["mode"]
    assert json.loads(row["plan_json"])["steps"] == body["plan"]["steps"]
    assert row["started_at"]
    assert row["completed_at"]
    assert row["error_message"] is None


def test_unexpected_agent_error_is_persisted_as_failed(client, employee_headers, monkeypatch):
    monkeypatch.setattr(main, "run_agent", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    response = client.post(
        "/api/agent/run",
        headers=employee_headers,
        json={"goal": "测试异常任务"},
    )

    assert response.status_code == 500
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, planner_mode, error_message, completed_at FROM agent_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["status"] == "failed"
    assert row["planner_mode"] == "runtime_error"
    assert row["error_message"] == "RuntimeError"
    assert row["completed_at"]
