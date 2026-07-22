import json
from pathlib import Path

from app.db import get_conn, utc_now
from app.evaluation_dataset import load_evaluation_baseline, load_evaluation_dataset
from app.evaluation_gate import QualityGatePolicy, evaluate_quality_gate
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


def seed_small_gate_dataset():
    seed_policy_document()
    with get_conn() as conn:
        conn.execute("DELETE FROM evaluation_cases")
        conn.execute(
            """
            INSERT INTO evaluation_cases(
                case_key, dataset_version, category, question,
                expected_keywords, expected_documents, should_answer, created_at
            )
            VALUES
                ('test-leave', 'test-v1', 'policy', ?, ?, ?, 1, ?),
                ('test-refusal', 'test-v1', 'abstention', ?, '[]', '[]', 0, ?)
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


def test_versioned_golden_dataset_is_valid_and_stable():
    dataset = load_evaluation_dataset()
    baseline = load_evaluation_baseline()

    assert dataset["version"] == "enterprise-rag-golden-v1"
    assert len(dataset["cases"]) == 5
    assert len(dataset["fingerprint"]) == 64
    assert len({item["key"] for item in dataset["cases"]}) == 5
    assert baseline["dataset_version"] == dataset["version"]
    assert baseline["dataset_fingerprint"] == dataset["fingerprint"]
    assert baseline["top_k"] == 5
    assert set(baseline["metrics"].values()) == {1.0}


def test_quality_gate_reports_threshold_and_regression_failures():
    summary = {
        "total": 4,
        "recall_at_k": 0.79,
        "mrr": 0.80,
        "answer_accuracy": 0.75,
        "abstention_accuracy": 1.0,
    }
    baseline = {
        "id": 11,
        "recall_at_k": 0.90,
        "mrr": 0.82,
        "answer_accuracy": 0.90,
        "abstention_accuracy": 1.0,
    }

    gate = evaluate_quality_gate(summary, QualityGatePolicy(), baseline)

    assert gate["status"] == "failed"
    assert set(gate["failed_metrics"]) == {"total", "recall_at_k", "answer_accuracy"}
    assert gate["baseline_run_id"] == 11
    assert gate["baseline_reference"] == 11
    assert gate["metric_deltas"]["recall_at_k"] == -0.11


def test_batch_gate_automatically_uses_latest_compatible_baseline(client, admin_headers):
    seed_small_gate_dataset()
    payload = {
        "minimum_cases": 2,
        "thresholds": {
            "recall_at_k": 1.0,
            "mrr": 1.0,
            "answer_accuracy": 1.0,
            "abstention_accuracy": 1.0,
        },
    }

    first = client.post("/api/evaluation/batch/run", headers=admin_headers, json=payload)
    second = client.post("/api/evaluation/batch/run", headers=admin_headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["gate"]["status"] == "passed"
    assert second.json()["gate"]["baseline_run_id"] == first.json()["run_id"]
    assert set(second.json()["gate"]["metric_deltas"].values()) == {0.0}
    with get_conn() as conn:
        stored = conn.execute(
            """
            SELECT gate_status, baseline_run_id, dataset_hash, thresholds_json
            FROM batch_eval_runs WHERE id = ?
            """,
            (second.json()["run_id"],),
        ).fetchone()
    assert stored["gate_status"] == "passed"
    assert stored["baseline_run_id"] == first.json()["run_id"]
    assert len(stored["dataset_hash"]) == 64
    assert json.loads(stored["thresholds_json"])["mrr"] == 1.0


def test_golden_cases_are_read_only_but_custom_cases_remain_editable(client, admin_headers):
    listing = client.get("/api/evaluation/cases?page=1&page_size=10", headers=admin_headers)
    golden = next(item for item in listing.json()["items"] if item["is_golden"])

    blocked = client.patch(
        f"/api/evaluation/cases/{golden['id']}",
        headers=admin_headers,
        json={"question": "篡改黄金用例", "category": "custom"},
    )
    created = client.post(
        "/api/evaluation/cases",
        headers=admin_headers,
        json={"question": "自定义测试问题", "category": "regression"},
    )
    updated = client.patch(
        f"/api/evaluation/cases/{created.json()['id']}",
        headers=admin_headers,
        json={"question": "自定义测试问题 V2", "category": "regression"},
    )
    golden_gate = client.post("/api/evaluation/batch/run", headers=admin_headers, json={})

    assert blocked.status_code == 409
    assert created.status_code == 200
    assert created.json()["is_golden"] is False
    assert updated.status_code == 200
    assert updated.json()["question"] == "自定义测试问题 V2"
    assert golden_gate.status_code == 200
    assert golden_gate.json()["summary"]["total"] == 5
    assert golden_gate.json()["gate"]["baseline_reference"] == "enterprise-rag-approved-baseline-v1"


def test_ci_runs_and_uploads_the_quality_gate_report():
    workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )

    assert "python -m app.eval_gate_cli" in workflow
    assert "rag-quality-gate-report" in workflow
    assert "actions/upload-artifact@v4" in workflow


def test_latest_quality_gate_has_a_single_frontend_render_owner():
    frontend = (Path(__file__).resolve().parents[2] / "frontend" / "app.js").read_text(encoding="utf-8")
    analytics_renderer = frontend.split("function renderAnalytics()", 1)[1].split(
        "function renderBarChart", 1
    )[0]
    batch_loader = frontend.split("async function loadBatchRuns()", 1)[1].split(
        "function renderBatchRuns", 1
    )[0]

    assert '$("#batchSummary")' not in analytics_renderer
    assert "renderLatestQualityGate(state.batchRuns[0])" in batch_loader
    assert "function renderLatestQualityGate(latest)" in batch_loader
