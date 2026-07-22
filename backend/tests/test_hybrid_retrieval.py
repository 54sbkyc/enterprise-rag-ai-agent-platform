import json

from app import search
from app.db import get_conn, utc_now
from app.text_processing import token_counts


def insert_chunk(title: str, content: str, *, level: str = "internal", embedding=None, model=None):
    with get_conn() as conn:
        document_id = conn.execute(
            """
            INSERT INTO documents(
                title, filename, file_type, storage_path, access_level,
                status, chunk_count, version, created_at
            )
            VALUES (?, ?, 'md', 'test', ?, 'ready', 1, 1, ?)
            """,
            (title, f"{title}.md", level, utc_now()),
        ).lastrowid
        chunk_id = conn.execute(
            """
            INSERT INTO chunks(
                document_id, chunk_index, content, token_json,
                embedding_json, embedding_model, content_hash, created_at
            )
            VALUES (?, 0, ?, ?, ?, ?, 'hash', ?)
            """,
            (
                document_id,
                content,
                json.dumps(token_counts(content), ensure_ascii=False),
                json.dumps(embedding or []),
                model,
                utc_now(),
            ),
        ).lastrowid
    return document_id, chunk_id


def test_bm25_ranks_relevant_policy_and_exposes_scores():
    insert_chunk("请假制度", "员工事假应至少提前一个工作日申请，由直属主管审批。")
    insert_chunk("设备制度", "员工领取电脑需要在资产管理系统登记。")

    hits = search.search_chunks("事假提前多久申请", 5, ["internal"])

    assert hits
    assert hits[0].document_title == "请假制度"
    assert hits[0].retrieval_mode == "bm25"
    assert hits[0].bm25_score > 0
    assert hits[0].vector_score == 0
    assert hits[0].rerank_score >= 0


def test_field_weighted_bm25_uses_title_to_resolve_generic_content_distractors():
    insert_chunk(
        "合同审批与风险控制指南",
        "合同发起人需提交合同正文、商务条款说明、报价依据、交付范围和风险说明。",
        level="sensitive",
    )
    insert_chunk(
        "销售报价策略",
        "常规折扣需要提交审批材料，说明客户背景、回款计划和交付风险。",
        level="sensitive",
    )
    insert_chunk(
        "数据管理制度",
        "敏感资料对外发送前需要提交申请并经过部门负责人审批。",
        level="sensitive",
    )

    hits = search.search_chunks("合同审批需要提交哪些材料？", 3, ["sensitive"])

    assert hits[0].document_title == "合同审批与风险控制指南"
    assert hits[0].bm25_score > hits[1].bm25_score


def test_vector_recall_finds_semantic_match_without_lexical_overlap(monkeypatch):
    insert_chunk("差旅制度", "出差住宿标准按照城市等级和岗位级别执行。", embedding=[1.0, 0.0], model="demo")
    insert_chunk("设备制度", "笔记本电脑需要通过资产系统登记。", embedding=[0.0, 1.0], model="demo")
    monkeypatch.setattr(search, "embed_query", lambda _text, _model: [1.0, 0.0])

    hits = search.search_chunks("完全不同的语义问法", 5, ["internal"])

    assert hits
    assert hits[0].document_title == "差旅制度"
    assert hits[0].retrieval_mode == "hybrid"
    assert hits[0].vector_score == 1.0
    assert all(hit.document_title != "设备制度" for hit in hits)


def test_hybrid_retrieval_still_enforces_document_access_levels(monkeypatch):
    insert_chunk("公开制度", "公开流程说明", level="public", embedding=[0.8, 0.2], model="demo")
    insert_chunk("敏感合同", "内部合同金额和付款条款", level="sensitive", embedding=[1.0, 0.0], model="demo")
    monkeypatch.setattr(search, "embed_query", lambda _text, _model: [1.0, 0.0])

    employee_hits = search.search_chunks("合同付款", 5, ["public", "internal"])
    manager_hits = search.search_chunks("合同付款", 5, ["public", "internal", "sensitive"])

    assert all(hit.document_title != "敏感合同" for hit in employee_hits)
    assert any(hit.document_title == "敏感合同" for hit in manager_hits)


def test_search_debug_api_explains_bm25_and_rerank(client, admin_headers):
    insert_chunk("请假制度", "员工事假应至少提前一个工作日申请，由直属主管审批。")

    response = client.get("/api/search?q=事假提前多久&top_k=3", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["explanation"]["retrieval_mode"] == "bm25"
    assert "BM25" in body["explanation"]["algorithm"]
    hit = body["hits"][0]
    assert set(hit["score_breakdown"]) == {"bm25", "vector", "rerank", "final"}
