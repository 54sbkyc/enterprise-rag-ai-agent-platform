import json

from app.db import _seed_evaluation_cases, get_conn, utc_now
from app.evaluation_metrics import evaluate_case_signals, reciprocal_rank, retrieval_recall
from app.text_processing import token_counts


def seed_policy_document():
    with get_conn() as conn:
        document_id = conn.execute(
            """
            INSERT INTO documents(
                title, filename, file_type, storage_path, access_level,
                status, chunk_count, version, created_at
            )
            VALUES ('请假制度', 'leave.md', 'md', 'test', 'internal', 'ready', 1, 1, ?)
            """,
            (utc_now(),),
        ).lastrowid
        content = "员工事假应至少提前一个工作日申请，由直属主管审批。"
        conn.execute(
            """
            INSERT INTO chunks(document_id, chunk_index, content, token_json, created_at)
            VALUES (?, 0, ?, ?, ?)
            """,
            (document_id, content, json.dumps(token_counts(content), ensure_ascii=False), utc_now()),
        )


def test_retrieval_metrics_use_expected_document_rank():
    citations = [
        {"document_title": "设备制度"},
        {"document_title": "请假制度 V2"},
        {"document_title": "差旅制度"},
    ]

    assert retrieval_recall(citations, ["请假制度", "差旅制度"]) == 1.0
    assert reciprocal_rank(citations, ["请假制度"]) == 0.5


def test_case_signals_measure_answer_and_abstention():
    answered = evaluate_case_signals(
        answer="员工事假应提前一个工作日申请。",
        confidence=0.8,
        citations=[{"document_title": "请假制度", "document_access_level": "internal"}],
        expected_keywords=["提前", "一个工作日"],
        expected_documents=["请假制度"],
        should_answer=True,
        allowed_access_levels=["public", "internal"],
    )
    refused = evaluate_case_signals(
        answer="资料库中未检索到足够依据，无法给出可靠答案。",
        confidence=0.0,
        citations=[],
        expected_keywords=[],
        expected_documents=[],
        should_answer=False,
        allowed_access_levels=["public", "internal"],
    )

    assert answered.answer_correct == 1
    assert answered.abstention_correct == 1
    assert answered.retrieval_recall == 1.0
    assert answered.reciprocal_rank == 1.0
    assert answered.access_control_correct == 1
    assert refused.answer_correct == 1
    assert refused.abstention_correct == 1
    assert refused.retrieval_recall is None
    assert refused.access_control_correct == 1


def test_case_signals_fail_when_a_citation_exceeds_the_actor_scope():
    signals = evaluate_case_signals(
        answer="合同审批需要法务意见。",
        confidence=0.8,
        citations=[{"document_title": "核心合同", "document_access_level": "sensitive"}],
        expected_keywords=["法务意见"],
        expected_documents=["核心合同"],
        should_answer=True,
        allowed_access_levels=["public", "internal"],
    )

    assert signals.answer_correct == 1
    assert signals.access_control_correct == 0


def test_batch_evaluation_returns_practical_quality_metrics(client, admin_headers):
    seed_policy_document()
    with get_conn() as conn:
        conn.execute("DELETE FROM evaluation_cases")
        conn.execute(
            """
            INSERT INTO evaluation_cases(
                actor_role, question, expected_keywords, expected_documents, should_answer, created_at
            )
            VALUES ('employee', ?, ?, ?, 1, ?), ('employee', ?, '[]', '[]', 0, ?)
            """,
            (
                "员工事假需要提前多久申请？",
                json.dumps(["提前", "一个工作日"], ensure_ascii=False),
                json.dumps(["请假制度"], ensure_ascii=False),
                utc_now(),
                "火星差旅如何报销？",
                utc_now(),
            ),
        )

    response = client.post(
        "/api/evaluation/batch/run",
        headers=admin_headers,
        json={
            "include_custom": True,
            "minimum_cases": 2,
            "thresholds": {
                "recall_at_k": 1.0,
                "mrr": 1.0,
                "answer_accuracy": 1.0,
                "abstention_accuracy": 1.0,
                "access_control_accuracy": 1.0,
            },
        },
    )

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["recall_at_k"] == 1.0
    assert summary["mrr"] == 1.0
    assert summary["answer_accuracy"] == 1.0
    assert summary["abstention_accuracy"] == 1.0
    assert summary["access_control_accuracy"] == 1.0
    assert response.json()["gate"]["status"] == "passed"
    assert response.json()["gate"]["baseline_run_id"] is None
    with get_conn() as conn:
        run = conn.execute(
            """
            SELECT recall_at_k, mrr, answer_accuracy, abstention_accuracy, access_control_accuracy
            FROM batch_eval_runs
            """
        ).fetchone()
        results = conn.execute(
            "SELECT actor_role, access_control_correct FROM batch_eval_results ORDER BY id"
        ).fetchall()
    assert dict(run) == {
        "recall_at_k": 1.0,
        "mrr": 1.0,
        "answer_accuracy": 1.0,
        "abstention_accuracy": 1.0,
        "access_control_accuracy": 1.0,
    }
    assert [dict(item) for item in results] == [
        {"actor_role": "employee", "access_control_correct": 1},
        {"actor_role": "employee", "access_control_correct": 1},
    ]


def test_legacy_builtin_cases_are_migrated_to_current_document_sources():
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE evaluation_cases
            SET expected_documents = '["ordinary_enterprise_handbook"]'
            WHERE question = '员工请假需要提前多久申请？'
            """
        )
        conn.execute(
            "DELETE FROM evaluation_cases WHERE question = '核心合作合同审批需要提交哪些材料？'"
        )
        conn.execute(
            """
            INSERT INTO evaluation_cases(
                question, expected_keywords, expected_documents, should_answer, created_at
            )
            VALUES ('合同总价是多少？', '["已脱敏", "尾款"]', '["sensitive_contract_note"]', 1, ?)
            """,
            (utc_now(),),
        )
        _seed_evaluation_cases(conn)
        leave_case = conn.execute(
            """
            SELECT expected_documents FROM evaluation_cases
            WHERE question = '员工请假需要提前多久申请？'
            """
        ).fetchone()
        contract_case = conn.execute(
            """
            SELECT case_key, dataset_version, expected_documents FROM evaluation_cases
            WHERE question = '合同审批需要提交哪些材料？'
            """
        ).fetchone()

    assert "enterprise_suite_attendance_leave.md" in leave_case["expected_documents"]
    assert contract_case is not None
    assert contract_case["case_key"] == "contract-approval-materials"
    assert contract_case["dataset_version"] == "enterprise-rag-golden-v2"
    assert "enterprise_suite_contract_risk.md" in contract_case["expected_documents"]
