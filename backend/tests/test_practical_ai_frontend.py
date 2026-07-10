from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_frontend_exposes_embedding_rebuild_and_index_status():
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'id="rebuildEmbeddingsBtn"' in markup
    assert 'id="embeddingRebuildStatus"' in markup
    assert 'api("/api/documents/embeddings/rebuild"' in script
    assert "embedding_status" in script


def test_frontend_renders_retrieval_and_batch_quality_metrics():
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'id="caseShouldAnswer"' in markup
    assert "data-case-should-answer" in script
    assert "score_breakdown" in script
    assert "Recall@K" in script
    assert "MRR" in script
    assert "拒答准确率" in script


def test_frontend_renders_agent_plan_and_execution_reliability():
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'id="agentPlanSummary"' in markup
    assert "result.plan" in script
    assert "call.attempts" in script
    assert "call.duration_ms" in script
