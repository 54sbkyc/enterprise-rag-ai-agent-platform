from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_frontend_declares_agent_workspace_surface():
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert 'data-route="agent"' in markup
    assert 'id="page-agent"' in markup
    assert 'id="agentGoalInput"' in markup
    assert 'id="runAgentBtn"' in markup
    assert 'id="agentToolTimeline"' in markup
    assert 'id="agentRunHistory"' in markup


def test_frontend_wires_agent_run_and_history_api():
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'agent: { title: "智能体工作台"' in script
    assert 'agent: "qa.use"' in script
    assert 'state.agentRuns' in script
    assert 'api("/api/agent/tasks"' in script
    assert 'api(`/api/agent/runs/${runId}`)' in script
    assert 'api(`/api/agent/runs/${runId}/cancel`' in script
    assert 'id="cancelAgentBtn"' in markup
    assert 'api(`/api/agent/runs?page=${paging.page}&page_size=${paging.pageSize}`)' in script
    assert 'function renderAgentToolTimeline' in script
    assert 'function renderAgentRuns' in script
