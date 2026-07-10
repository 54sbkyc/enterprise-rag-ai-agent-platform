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


def test_employee_question_creates_quality_assessment(client, employee_headers):
    seed_policy_document()

    response = client.post(
        "/api/ask",
        headers=employee_headers,
        json={"question": "员工事假需要提前多久申请？"},
    )

    assert response.status_code == 200
    log_id = response.json()["log_id"]
    with get_conn() as conn:
        assessment = conn.execute(
            "SELECT quality_level, status FROM qa_quality_assessments WHERE log_id = ?",
            (log_id,),
        ).fetchone()
    assert assessment is not None
    assert assessment["status"] == "completed"


def test_negative_feedback_recalculates_and_creates_gap(client, employee_headers):
    response = client.post(
        "/api/ask",
        headers=employee_headers,
        json={"question": "公司量子卫星报销规则是什么？"},
    )
    log_id = response.json()["log_id"]

    feedback = client.post(
        "/api/qa-feedback",
        headers=employee_headers,
        json={"log_id": log_id, "rating": "unhelpful"},
    )

    assert feedback.status_code == 200
    with get_conn() as conn:
        assessment = conn.execute(
            "SELECT quality_level, feedback_score FROM qa_quality_assessments WHERE log_id = ?",
            (log_id,),
        ).fetchone()
        gap = conn.execute(
            "SELECT id FROM knowledge_gaps WHERE source_log_id = ? AND status = 'open'",
            (log_id,),
        ).fetchone()
    assert assessment["quality_level"] == "review"
    assert assessment["feedback_score"] == 0
    assert gap is not None


def test_standard_evaluation_does_not_create_employee_log(client, admin_headers):
    seed_policy_document()
    with get_conn() as conn:
        before = conn.execute("SELECT COUNT(*) AS count FROM qa_logs").fetchone()["count"]

    response = client.post(
        "/api/evaluate",
        headers=admin_headers,
        json={
            "question": "员工事假需要提前多久申请？",
            "expected_keywords": ["提前", "一个工作日"],
            "expected_documents": ["员工请假制度"],
        },
    )

    assert response.status_code == 200
    with get_conn() as conn:
        after = conn.execute("SELECT COUNT(*) AS count FROM qa_logs").fetchone()["count"]
    assert after == before


def test_quality_assessment_list_is_paginated(client, employee_headers, tech_headers):
    for index in range(3):
        response = client.post(
            "/api/ask",
            headers=employee_headers,
            json={"question": f"未收录制度问题 {index}"},
        )
        assert response.status_code == 200

    response = client.get(
        "/api/quality-assessments?page=1&page_size=2",
        headers=tech_headers,
    )

    assert response.status_code == 200
    result = response.json()
    assert result["total"] == 3
    assert len(result["items"]) == 2


def test_gap_recheck_saves_comparison_without_new_employee_log(
    client,
    employee_headers,
    tech_headers,
):
    response = client.post(
        "/api/ask",
        headers=employee_headers,
        json={"question": "员工事假需要提前多久申请？"},
    )
    log_id = response.json()["log_id"]
    with get_conn() as conn:
        gap_id = conn.execute(
            "SELECT id FROM knowledge_gaps WHERE source_log_id = ?",
            (log_id,),
        ).fetchone()["id"]
        before_logs = conn.execute("SELECT COUNT(*) AS count FROM qa_logs").fetchone()["count"]
    seed_policy_document()

    recheck = client.post(
        f"/api/knowledge-gaps/{gap_id}/recheck",
        headers=tech_headers,
    )

    assert recheck.status_code == 200
    assert recheck.json()["after_score"] >= 0
    with get_conn() as conn:
        gap = conn.execute(
            "SELECT before_score, after_score, reviewed_at FROM knowledge_gaps WHERE id = ?",
            (gap_id,),
        ).fetchone()
        after_logs = conn.execute("SELECT COUNT(*) AS count FROM qa_logs").fetchone()["count"]
    assert gap["before_score"] is not None
    assert gap["after_score"] is not None
    assert gap["reviewed_at"] is not None
    assert after_logs == before_logs


def test_gap_workflow_requires_recheck_before_resolving(client, employee_headers, tech_headers):
    response = client.post(
        "/api/ask",
        headers=employee_headers,
        json={"question": "尚未收录的项目交付规范是什么？"},
    )
    log_id = response.json()["log_id"]
    with get_conn() as conn:
        gap_id = conn.execute(
            "SELECT id FROM knowledge_gaps WHERE source_log_id = ?",
            (log_id,),
        ).fetchone()["id"]

    claim = client.patch(
        f"/api/knowledge-gaps/{gap_id}",
        headers=tech_headers,
        json={
            "status": "processing",
            "resolution_action": "补充项目交付规范文档",
        },
    )
    premature_resolve = client.patch(
        f"/api/knowledge-gaps/{gap_id}",
        headers=tech_headers,
        json={"status": "resolved"},
    )
    close_without_action = client.patch(
        f"/api/knowledge-gaps/{gap_id}",
        headers=tech_headers,
        json={
            "status": "closed",
            "resolution_action": "确认该问题不属于企业制度知识范围",
        },
    )

    assert claim.status_code == 200
    assert claim.json()["assigned_to"] is not None
    assert claim.json()["resolution_action"] == "补充项目交付规范文档"
    assert premature_resolve.status_code == 400
    assert close_without_action.status_code == 200
    assert close_without_action.json()["status"] == "closed"
