import time
from threading import Event

from app import agent
from app.auth import hash_password
from app.db import get_conn, utc_now


def completed_result(answer: str = "任务完成") -> dict:
    return {
        "status": "completed",
        "final_answer": answer,
        "tool_calls": [],
        "plan": {
            "mode": "deterministic",
            "steps": [],
            "fallback_reason": None,
            "requested_model": None,
        },
        "error_message": None,
    }


def failed_result() -> dict:
    result = completed_result("任务失败")
    result["status"] = "failed"
    result["error_message"] = "test_failure"
    return result


def wait_for_status(client, headers, run_id: int, expected: set[str], timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/agent/runs/{run_id}", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] in expected:
            return body
        time.sleep(0.02)
    raise AssertionError(f"Agent task #{run_id} did not reach {sorted(expected)}")


def test_async_agent_task_is_idempotent(client, employee_headers, monkeypatch):
    started = Event()
    release = Event()
    calls = {"count": 0}

    def slow_agent(*_args, **_kwargs):
        calls["count"] += 1
        started.set()
        assert release.wait(2)
        return completed_result()

    monkeypatch.setattr(agent, "run_agent", slow_agent)
    monkeypatch.setattr(agent, "AGENT_TASK_MAX_ACTIVE_PER_USER", 1)
    payload = {"goal": "验证幂等任务", "top_k": 5, "idempotency_key": "task-idempotent-001"}

    first = client.post("/api/agent/tasks", headers=employee_headers, json=payload)
    assert first.status_code == 202, first.text
    assert started.wait(1)
    second = client.post("/api/agent/tasks", headers=employee_headers, json=payload)

    assert second.status_code == 202, second.text
    assert second.json()["run_id"] == first.json()["run_id"]
    assert second.json()["reused"] is True
    limited = client.post(
        "/api/agent/tasks",
        headers=employee_headers,
        json={"goal": "另一个并发任务", "idempotency_key": "task-idempotent-002"},
    )
    assert limited.status_code == 429
    release.set()
    terminal = wait_for_status(client, employee_headers, first.json()["run_id"], {"completed"})
    assert terminal["execution_mode"] == "async"
    assert calls["count"] == 1

    conflict = client.post(
        "/api/agent/tasks",
        headers=employee_headers,
        json={**payload, "goal": "使用同一幂等键的其他任务"},
    )
    assert conflict.status_code == 409


def test_async_agent_task_can_be_cancelled(client, employee_headers, monkeypatch):
    started = Event()

    def cancellable_agent(*_args, cancel_check=None, **_kwargs):
        started.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if cancel_check and cancel_check():
                return agent.cancelled_result([], agent.pending_plan())
            time.sleep(0.01)
        return completed_result()

    monkeypatch.setattr(agent, "run_agent", cancellable_agent)
    created = client.post(
        "/api/agent/tasks",
        headers=employee_headers,
        json={"goal": "验证任务取消", "idempotency_key": "task-cancel-001"},
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["run_id"]
    assert started.wait(1)

    cancelled = client.post(f"/api/agent/runs/{run_id}/cancel", headers=employee_headers)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] in {"cancel_requested", "cancelled"}
    terminal = wait_for_status(client, employee_headers, run_id, {"cancelled"})
    assert terminal["cancel_requested_at"]
    assert "已取消" in terminal["final_answer"]


def test_failed_agent_task_can_be_retried(client, employee_headers, monkeypatch):
    calls = {"count": 0}

    def flaky_agent(*_args, **_kwargs):
        calls["count"] += 1
        return failed_result() if calls["count"] == 1 else completed_result("重试成功")

    monkeypatch.setattr(agent, "run_agent", flaky_agent)
    created = client.post(
        "/api/agent/tasks",
        headers=employee_headers,
        json={"goal": "验证失败重试", "idempotency_key": "task-retry-source-001"},
    )
    assert created.status_code == 202, created.text
    source = wait_for_status(client, employee_headers, created.json()["run_id"], {"failed"})

    retried = client.post(
        f"/api/agent/runs/{source['id']}/retry",
        headers=employee_headers,
        json={"idempotency_key": "task-retry-target-001"},
    )
    assert retried.status_code == 202, retried.text
    assert retried.json()["parent_run_id"] == source["id"]
    terminal = wait_for_status(client, employee_headers, retried.json()["run_id"], {"completed"})
    assert terminal["final_answer"] == "重试成功"
    assert calls["count"] == 2


def test_interrupted_agent_tasks_are_recovered_on_startup():
    with get_conn() as conn:
        user = dict(conn.execute("SELECT * FROM users WHERE username = 'employee'").fetchone())
    cancelled_id = agent.create_agent_run(
        "等待取消的任务",
        user,
        status="queued",
        execution_mode="async",
    )
    failed_id = agent.create_agent_run(
        "被重启中断的任务",
        user,
        status="running",
        execution_mode="async",
    )
    assert agent.request_agent_run_cancel(cancelled_id) == "cancel_requested"

    agent.recover_interrupted_agent_runs()

    with get_conn() as conn:
        cancelled = conn.execute(
            "SELECT status, error_message, completed_at FROM agent_runs WHERE id = ?",
            (cancelled_id,),
        ).fetchone()
        failed = conn.execute(
            "SELECT status, error_message, completed_at FROM agent_runs WHERE id = ?",
            (failed_id,),
        ).fetchone()
    assert cancelled["status"] == "cancelled"
    assert cancelled["error_message"] is None
    assert cancelled["completed_at"]
    assert failed["status"] == "failed"
    assert failed["error_message"] == "server_restarted"
    assert failed["completed_at"]


def test_agent_run_detail_is_private_to_owner_and_managers(client, employee_headers):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users(username, password_hash, role, display_name, is_active, created_at)
            VALUES ('employee_two', ?, 'employee', '另一名员工', 1, ?)
            """,
            (hash_password("user456"), utc_now()),
        )
    login = client.post("/api/auth/login", json={"username": "employee_two", "password": "user456"})
    other_headers = {"Authorization": f"Bearer {login.json()['token']}"}
    created = client.post(
        "/api/agent/run",
        headers=employee_headers,
        json={"goal": "验证任务隔离"},
    )
    run_id = created.json()["run_id"]

    detail = client.get(f"/api/agent/runs/{run_id}", headers=other_headers)
    cancel = client.post(f"/api/agent/runs/{run_id}/cancel", headers=other_headers)

    assert detail.status_code == 404
    assert cancel.status_code == 404
