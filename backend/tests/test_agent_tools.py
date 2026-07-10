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


def test_agent_run_searches_knowledge_base_and_persists_tool_calls(client, employee_headers):
    seed_policy_document()

    response = client.post(
        "/api/agent/run",
        headers=employee_headers,
        json={"goal": "员工事假需要提前多久申请？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["run_id"] > 0
    tool_names = [call["tool_name"] for call in body["tool_calls"]]
    assert tool_names[:3] == ["security_check", "search_knowledge_base", "generate_grounded_answer"]
    assert body["tool_calls"][1]["output"]["hit_count"] >= 1
    assert "提前一个工作日" in body["final_answer"]

    with get_conn() as conn:
        row = conn.execute(
            "SELECT goal, status, tool_calls_json FROM agent_runs WHERE id = ?",
            (body["run_id"],),
        ).fetchone()
    assert row["goal"] == "员工事假需要提前多久申请？"
    assert row["status"] == "completed"
    assert json.loads(row["tool_calls_json"])[1]["tool_name"] == "search_knowledge_base"


def test_agent_run_can_create_knowledge_gap_for_manager(client, tech_headers):
    response = client.post(
        "/api/agent/run",
        headers=tech_headers,
        json={"goal": "请创建知识缺口：公司量子卫星报销规则是什么？"},
    )

    assert response.status_code == 200
    body = response.json()
    gap_call = next(call for call in body["tool_calls"] if call["tool_name"] == "create_knowledge_gap")
    assert gap_call["status"] == "completed"
    assert gap_call["output"]["gap_id"] > 0
    assert "知识缺口" in body["final_answer"]

    with get_conn() as conn:
        gap = conn.execute(
            "SELECT question, status, note FROM knowledge_gaps WHERE id = ?",
            (gap_call["output"]["gap_id"],),
        ).fetchone()
    assert "公司量子卫星报销规则是什么" in gap["question"]
    assert gap["status"] == "open"
    assert "Agent" in gap["note"]


def test_agent_log_tool_respects_audit_permission(client, employee_headers, admin_headers):
    client.post(
        "/api/ask",
        headers=employee_headers,
        json={"question": "公司没有收录的问题是什么？"},
    )

    employee_response = client.post(
        "/api/agent/run",
        headers=employee_headers,
        json={"goal": "查看最近问答日志"},
    )
    admin_response = client.post(
        "/api/agent/run",
        headers=admin_headers,
        json={"goal": "查看最近问答日志"},
    )

    assert employee_response.status_code == 200
    employee_log_call = next(
        call for call in employee_response.json()["tool_calls"] if call["tool_name"] == "query_recent_logs"
    )
    assert employee_log_call["status"] == "skipped"
    assert "权限" in employee_response.json()["final_answer"]

    assert admin_response.status_code == 200
    admin_log_call = next(call for call in admin_response.json()["tool_calls"] if call["tool_name"] == "query_recent_logs")
    assert admin_log_call["status"] == "completed"
    assert admin_log_call["output"]["count"] >= 1


def test_agent_runs_are_listed_for_current_user_and_managers(client, employee_headers, admin_headers):
    employee_run = client.post(
        "/api/agent/run",
        headers=employee_headers,
        json={"goal": "员工事假需要提前多久申请？"},
    )
    admin_run = client.post(
        "/api/agent/run",
        headers=admin_headers,
        json={"goal": "查看最近问答日志"},
    )
    assert employee_run.status_code == 200
    assert admin_run.status_code == 200

    employee_list = client.get("/api/agent/runs", headers=employee_headers)
    admin_list = client.get("/api/agent/runs", headers=admin_headers)

    assert employee_list.status_code == 200
    assert employee_list.json()["total"] == 1
    assert employee_list.json()["items"][0]["id"] == employee_run.json()["run_id"]
    assert employee_list.json()["items"][0]["tool_calls"]

    assert admin_list.status_code == 200
    assert admin_list.json()["total"] == 2
    assert {item["id"] for item in admin_list.json()["items"]} == {
        employee_run.json()["run_id"],
        admin_run.json()["run_id"],
    }
