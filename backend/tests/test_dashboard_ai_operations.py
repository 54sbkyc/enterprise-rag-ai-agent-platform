from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_dashboard_summarizes_agent_operations(client, employee_headers, admin_headers):
    run_response = client.post(
        "/api/agent/run",
        headers=employee_headers,
        json={"goal": "summarize onboarding policy"},
    )
    assert run_response.status_code == 200
    run_body = run_response.json()

    dashboard_response = client.get("/api/dashboard", headers=admin_headers)

    assert dashboard_response.status_code == 200
    agent_metrics = dashboard_response.json()["agent_metrics"]
    assert agent_metrics["run_count"] == 1
    assert agent_metrics["completed_run_count"] == 1
    assert agent_metrics["total_tool_calls"] == len(run_body["tool_calls"])
    assert agent_metrics["skipped_tool_call_count"] >= 1
    assert agent_metrics["recent_runs"][0]["id"] == run_body["run_id"]
    assert agent_metrics["recent_runs"][0]["tool_count"] == len(run_body["tool_calls"])


def test_frontend_declares_dashboard_ai_operations_surface():
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'id="dashboardAiOpsPanel"' in markup
    assert 'id="dashAiTokens"' in markup
    assert 'id="dashAiCost"' in markup
    assert 'id="dashAgentRuns"' in markup
    assert 'id="dashToolCalls"' in markup
    assert 'id="dashAgentRecentRuns"' in markup
    assert "function renderDashboardAiOps" in script
    assert "state.dashboard.agent_metrics" in script
    assert "stats.ai_usage" in script
