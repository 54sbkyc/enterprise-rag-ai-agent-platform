from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_qa_page_declares_trace_and_usage_panels():
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert 'id="qaTracePanel"' in markup
    assert 'id="qaTraceList"' in markup
    assert 'id="qaUsagePanel"' in markup
    assert 'id="qaUsageGrid"' in markup
    assert "决策轨迹" in markup
    assert "调用用量" in markup


def test_frontend_renders_qa_trace_and_usage_from_ask_response():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function renderQaTrace" in script
    assert "function renderQaUsage" in script
    assert "renderQaTrace(result.agent_trace || [])" in script
    assert "renderQaUsage(result.usage || null)" in script
    assert "qa-trace-item" in script
    assert "usage-metric" in script
