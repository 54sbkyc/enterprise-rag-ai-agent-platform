from app.qa import assess_evidence_coverage, build_grounded_answer
from app.evaluation_metrics import is_refusal
from app.main import AskRequest, compute_answer
from app.search import SearchHit
from seed_enterprise_documents import seed_documents


def make_hit(content: str, title: str = "费用报销与差旅管理办法") -> SearchHit:
    return SearchHit(
        chunk_id=1,
        document_id=1,
        document_title=title,
        document_filename="policy.md",
        document_access_level="internal",
        chunk_index=0,
        content=content,
        score=0.92,
        matched_terms=[],
        query_terms=[],
        bm25_score=8.0,
        rerank_score=0.8,
    )


def test_missing_key_condition_triggers_grounded_refusal():
    question = "火星差旅费用如何报销？"
    hits = [make_hit("业务差旅费用应在七个工作日内提交票据并申请报销。")]

    answer, confidence, citations, generation = build_grounded_answer(question, hits)

    assert "未找到覆盖问题关键条件的明确依据" in answer
    assert confidence < 0.16
    assert citations
    assert generation["fallback_reason"] == "insufficient_evidence_coverage"
    assert "火星" in generation["missing_evidence_terms"]
    assert generation["evidence_coverage"] < 0.7
    assert is_refusal(answer, confidence, citations)


def test_supported_policy_question_passes_evidence_guardrail():
    question = "员工请假需要提前多久申请？"
    hits = [make_hit("员工请假应至少提前一个工作日申请。", "考勤与请假管理制度")]

    evidence = assess_evidence_coverage(question, hits)
    answer, confidence, _, generation = build_grounded_answer(question, hits)

    assert evidence["coverage"] >= 0.7
    assert "未找到覆盖问题关键条件的明确依据" not in answer
    assert "提前一个工作日" in answer
    assert confidence >= 0.16
    assert generation["fallback_reason"] != "insufficient_evidence_coverage"


def test_restricted_topic_guard_refuses_without_exposing_sensitive_metadata():
    seed_documents()

    employee_result = compute_answer(
        AskRequest(question="合同审批需要提交哪些材料？", top_k=5),
        {"id": 3, "role": "employee"},
    )
    verbose_employee_result = compute_answer(
        AskRequest(question="关于公司核心合作合同的审批流程，发起前总共要准备哪些业务、法务和财务材料？", top_k=5),
        {"id": 3, "role": "employee"},
    )
    admin_result = compute_answer(
        AskRequest(question="合同审批需要提交哪些材料？", top_k=5),
        {"id": 1, "role": "admin"},
    )
    expense_result = compute_answer(
        AskRequest(question="费用发生后多久提交报销？", top_k=5),
        {"id": 3, "role": "employee"},
    )

    assert employee_result["generation"]["fallback_reason"] == "restricted_access_scope"
    assert employee_result["citations"] == []
    assert "合同审批与风险控制指南" not in employee_result["answer"]
    assert is_refusal(employee_result["answer"], employee_result["confidence"], employee_result["citations"])
    assert verbose_employee_result["generation"]["fallback_reason"] == "restricted_access_scope"
    assert verbose_employee_result["citations"] == []
    assert any(item["document_access_level"] == "sensitive" for item in admin_result["citations"])
    assert "7 个工作日" in expense_result["answer"]
