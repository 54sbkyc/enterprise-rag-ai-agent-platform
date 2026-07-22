import json
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from .agent_planner import (
    TOOL_ANSWER,
    TOOL_GAP,
    TOOL_LOGS,
    TOOL_SEARCH,
    TOOL_SECURITY,
    plan_agent,
)
from .auth import allowed_access_levels
from .config import AGENT_TASK_MAX_ACTIVE_PER_USER
from .db import get_conn, utc_now
from .permissions import has_permission
from .qa import build_grounded_answer
from .search import search_chunks
from .security import inspect_question


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


AGENT_TOOL_TIMEOUT_SECONDS = _positive_int_env("AGENT_TOOL_TIMEOUT_SECONDS", 25)
AGENT_TOOL_MAX_ATTEMPTS = _positive_int_env("AGENT_TOOL_MAX_ATTEMPTS", 2)


class AgentTaskConflictError(ValueError):
    pass


class AgentTaskLimitError(RuntimeError):
    pass


def run_agent(
    goal: str,
    top_k: int,
    user: dict,
    cancel_check: Callable[[], bool] | None = None,
) -> dict:
    normalized_goal = goal.strip()
    plan = plan_agent(
        normalized_goal,
        can_manage_gaps=has_permission(user, "gaps.manage"),
        can_view_audit=has_permission(user, "audit.view"),
    )
    steps = list(plan.steps)
    tool_calls: list[dict] = []
    if cancellation_requested(cancel_check):
        return cancelled_result(tool_calls, plan.as_dict())

    success, security_result, meta = run_with_retry(lambda: inspect_question(normalized_goal))
    if not success:
        tool_calls.append(failed_tool_call(TOOL_SECURITY, {"goal": normalized_goal}, meta))
        return failed_result("安全检查工具执行失败。", tool_calls, plan.as_dict(), meta["error"])
    tool_calls.append(
        tool_call(
            TOOL_SECURITY,
            {"goal": normalized_goal},
            "passed" if security_result.allowed else "blocked",
            {"allowed": security_result.allowed, "reason": security_result.reason},
            meta["attempts"],
            meta["duration_ms"],
        )
    )
    if cancellation_requested(cancel_check):
        return cancelled_result(tool_calls, plan.as_dict())
    if not security_result.allowed:
        return {
            "status": "blocked",
            "final_answer": "该任务触发安全策略，Agent 已停止执行。",
            "tool_calls": tool_calls,
            "plan": plan.as_dict(),
            "error_message": None,
        }

    if TOOL_LOGS in steps:
        success, log_result, meta = run_with_retry(lambda: query_recent_logs(user))
        if not success:
            tool_calls.append(failed_tool_call(TOOL_LOGS, {"limit": 3}, meta))
            return failed_result("日志查询工具执行失败。", tool_calls, plan.as_dict(), meta["error"])
        status = "completed" if log_result["allowed"] else "skipped"
        tool_calls.append(
            tool_call(
                TOOL_LOGS,
                {"limit": 3},
                status,
                log_result["output"],
                meta["attempts"],
                meta["duration_ms"],
            )
        )
        if cancellation_requested(cancel_check):
            return cancelled_result(tool_calls, plan.as_dict())
        return {
            "status": "completed",
            "final_answer": log_result["answer"],
            "tool_calls": tool_calls,
            "plan": plan.as_dict(),
            "error_message": None,
        }

    access_levels = allowed_access_levels(user)
    success, hits, meta = run_with_retry(lambda: search_chunks(normalized_goal, top_k, access_levels))
    if not success:
        tool_calls.append(
            failed_tool_call(
                TOOL_SEARCH,
                {"query": normalized_goal, "top_k": top_k, "access_levels": access_levels},
                meta,
            )
        )
        return failed_result("知识库检索工具执行失败。", tool_calls, plan.as_dict(), meta["error"])
    tool_calls.append(
        tool_call(
            TOOL_SEARCH,
            {"query": normalized_goal, "top_k": top_k, "access_levels": access_levels},
            "completed",
            {
                "hit_count": len(hits),
                "top_score": round(hits[0].score, 4) if hits else 0,
                "retrieval_mode": hits[0].retrieval_mode if hits else "bm25",
                "top_documents": [serialize_hit(hit) for hit in hits[:3]],
            },
            meta["attempts"],
            meta["duration_ms"],
        )
    )
    if cancellation_requested(cancel_check):
        return cancelled_result(tool_calls, plan.as_dict())

    success, answer_result, meta = run_with_retry(lambda: build_grounded_answer(normalized_goal, hits))
    if not success:
        tool_calls.append(failed_tool_call(TOOL_ANSWER, {"citation_count": len(hits)}, meta))
        return failed_result("可信回答工具执行失败。", tool_calls, plan.as_dict(), meta["error"])
    answer, confidence, citations, generation = answer_result
    tool_calls.append(
        tool_call(
            TOOL_ANSWER,
            {"citation_count": len(citations)},
            "completed",
            {
                "confidence": round(confidence, 4),
                "answer_chars": len(answer),
                "generation_mode": generation["mode"],
                "model": generation["model"],
                "requested_model": generation.get("requested_model"),
                "fallback_reason": generation.get("fallback_reason"),
            },
            meta["attempts"],
            meta["duration_ms"],
        )
    )
    if cancellation_requested(cancel_check):
        return cancelled_result(tool_calls, plan.as_dict())

    if confidence < 0.16 and TOOL_GAP not in steps:
        steps.append(TOOL_GAP)
    gap_id = None
    if TOOL_GAP in steps:
        gap_call, gap_id = create_gap_if_allowed(normalized_goal, user)
        tool_calls.append(gap_call)
        if cancellation_requested(cancel_check):
            return cancelled_result(tool_calls, plan.as_dict())

    final_answer = answer
    if gap_id:
        final_answer = f"{answer}\n\nAgent 已创建知识缺口 #{gap_id}，可在知识优化模块继续处理。"
    plan_dict = plan.as_dict()
    plan_dict["steps"] = steps
    return {
        "status": "completed",
        "final_answer": final_answer,
        "tool_calls": tool_calls,
        "plan": plan_dict,
        "error_message": None,
    }


def cancellation_requested(cancel_check: Callable[[], bool] | None) -> bool:
    return bool(cancel_check and cancel_check())


def cancelled_result(calls: list[dict], plan: dict) -> dict:
    return {
        "status": "cancelled",
        "final_answer": "Agent 任务已取消，后续工具调用已停止。",
        "tool_calls": calls,
        "plan": plan,
        "error_message": None,
    }


def run_with_retry(callback):
    started = time.perf_counter()
    last_error = "tool_failed"
    for attempt in range(1, AGENT_TOOL_MAX_ATTEMPTS + 1):
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(callback)
        try:
            value = future.result(timeout=AGENT_TOOL_TIMEOUT_SECONDS)
            executor.shutdown(wait=True)
            return True, value, {
                "attempts": attempt,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "error": None,
            }
        except FutureTimeoutError:
            last_error = "tool_timeout"
            future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            last_error = "tool_execution_error"
            executor.shutdown(wait=True)
    return False, None, {
        "attempts": AGENT_TOOL_MAX_ATTEMPTS,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "error": last_error,
    }


def query_recent_logs(user: dict) -> dict:
    if not has_permission(user, "audit.view"):
        return {
            "allowed": False,
            "output": {"reason": "当前角色没有查看问答日志的权限"},
            "answer": "当前角色没有查看问答日志的权限，Agent 已跳过日志查询工具。",
        }
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, question, confidence, blocked, created_at
            FROM qa_logs ORDER BY id DESC LIMIT 3
            """
        ).fetchall()
    logs = [
        {
            "id": row["id"],
            "question": row["question"],
            "confidence": row["confidence"],
            "blocked": bool(row["blocked"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]
    answer = "最近还没有问答日志。" if not logs else "最近问答日志：" + "；".join(
        f"#{item['id']} {item['question']}" for item in logs
    )
    return {"allowed": True, "output": {"count": len(logs), "items": logs}, "answer": answer}


def create_gap_if_allowed(question: str, user: dict) -> tuple[dict, int | None]:
    started = time.perf_counter()
    gap_question = clean_gap_question(question)
    if not has_permission(user, "gaps.manage"):
        return (
            tool_call(
                TOOL_GAP,
                {"question": gap_question},
                "skipped",
                {"reason": "当前角色没有创建知识缺口的权限"},
                1,
                round((time.perf_counter() - started) * 1000, 2),
            ),
            None,
        )
    note = "Agent 根据用户任务或低置信回答自动创建"
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM knowledge_gaps WHERE status != 'resolved' AND question = ? LIMIT 1",
            (gap_question,),
        ).fetchone()
        if existing:
            gap_id = existing["id"]
            duplicate = True
        else:
            cursor = conn.execute(
                """
                INSERT INTO knowledge_gaps(question, source_log_id, status, note, created_by, created_at)
                VALUES (?, NULL, 'open', ?, ?, ?)
                """,
                (gap_question, note, user["id"], utc_now()),
            )
            gap_id = cursor.lastrowid
            duplicate = False
    return (
        tool_call(
            TOOL_GAP,
            {"question": gap_question},
            "completed",
            {"gap_id": gap_id, "duplicate": duplicate},
            1,
            round((time.perf_counter() - started) * 1000, 2),
        ),
        gap_id,
    )


def create_agent_run(
    goal: str,
    user: dict,
    *,
    status: str = "running",
    execution_mode: str = "sync",
    top_k: int = 5,
    idempotency_key: str | None = None,
    parent_run_id: int | None = None,
) -> int:
    created_at = utc_now()
    started_at = created_at if status == "running" else None
    with get_conn() as conn:
        return conn.execute(
            """
            INSERT INTO agent_runs(
                goal, status, final_answer, user_id, tool_calls_json, plan_json,
                planner_mode, started_at, execution_mode, top_k, idempotency_key,
                parent_run_id, updated_at, created_at
            )
            VALUES (?, ?, '', ?, '[]', '{}', 'pending', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                goal.strip(),
                status,
                user["id"],
                started_at,
                execution_mode,
                top_k,
                idempotency_key,
                parent_run_id,
                created_at,
                created_at,
            ),
        ).lastrowid


def finish_agent_run(run_id: int, result: dict) -> None:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT status FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        effective_result = result
        if current and current["status"] == "cancel_requested" and result["status"] != "cancelled":
            effective_result = cancelled_result(result.get("tool_calls", []), result.get("plan", {}))
        completed_at = utc_now()
        conn.execute(
            """
            UPDATE agent_runs
            SET status = ?, final_answer = ?, tool_calls_json = ?, plan_json = ?,
                planner_mode = ?, error_message = ?, completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                effective_result["status"],
                effective_result["final_answer"],
                json.dumps(effective_result["tool_calls"], ensure_ascii=False),
                json.dumps(effective_result["plan"], ensure_ascii=False),
                effective_result["plan"].get("mode", "unknown"),
                effective_result.get("error_message"),
                completed_at,
                completed_at,
                run_id,
            ),
        )


def create_or_get_agent_task(
    goal: str,
    top_k: int,
    user: dict,
    *,
    idempotency_key: str | None = None,
    parent_run_id: int | None = None,
) -> tuple[int, bool]:
    normalized_goal = goal.strip()
    normalized_key = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None
    created_at = utc_now()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if normalized_key:
            existing = conn.execute(
                """
                SELECT id, goal, top_k
                FROM agent_runs
                WHERE user_id = ? AND idempotency_key = ?
                LIMIT 1
                """,
                (user["id"], normalized_key),
            ).fetchone()
            if existing:
                if existing["goal"] != normalized_goal or existing["top_k"] != top_k:
                    raise AgentTaskConflictError("idempotency_key_payload_mismatch")
                return existing["id"], True
        active_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM agent_runs
            WHERE user_id = ? AND execution_mode = 'async'
              AND status IN ('queued', 'running', 'cancel_requested')
            """,
            (user["id"],),
        ).fetchone()["count"]
        if active_count >= AGENT_TASK_MAX_ACTIVE_PER_USER:
            raise AgentTaskLimitError("active_task_limit_reached")
        run_id = conn.execute(
            """
            INSERT INTO agent_runs(
                goal, status, final_answer, user_id, tool_calls_json, plan_json,
                planner_mode, execution_mode, top_k, idempotency_key,
                parent_run_id, updated_at, created_at
            )
            VALUES (?, 'queued', '', ?, '[]', '{}', 'pending', 'async', ?, ?, ?, ?, ?)
            """,
            (
                normalized_goal,
                user["id"],
                top_k,
                normalized_key,
                parent_run_id,
                created_at,
                created_at,
            ),
        ).lastrowid
    return run_id, False


def execute_agent_task(run_id: int, goal: str, top_k: int, user: dict) -> None:
    if not mark_agent_run_running(run_id):
        if agent_run_status(run_id) == "cancel_requested":
            finish_agent_run(run_id, cancelled_result([], pending_plan()))
        return
    try:
        result = run_agent(goal, top_k, user, cancel_check=lambda: is_agent_run_cancel_requested(run_id))
    except Exception as exc:
        result = runtime_error_result(exc)
    finish_agent_run(run_id, result)


def mark_agent_run_running(run_id: int) -> bool:
    started_at = utc_now()
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE agent_runs
            SET status = 'running', started_at = COALESCE(started_at, ?), updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (started_at, started_at, run_id),
        )
    return cursor.rowcount == 1


def request_agent_run_cancel(run_id: int) -> str | None:
    requested_at = utc_now()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT status FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        if row["status"] in {"queued", "running"}:
            conn.execute(
                """
                UPDATE agent_runs
                SET status = 'cancel_requested', cancel_requested_at = ?, updated_at = ?
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (requested_at, requested_at, run_id),
            )
            return "cancel_requested"
        return row["status"]


def is_agent_run_cancel_requested(run_id: int) -> bool:
    return agent_run_status(run_id) == "cancel_requested"


def agent_run_status(run_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT status FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    return row["status"] if row else None


def recover_interrupted_agent_runs() -> None:
    recovered_at = utc_now()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE agent_runs
            SET status = 'cancelled', final_answer = 'Agent 任务已取消，后续工具调用已停止。',
                error_message = NULL, completed_at = ?, updated_at = ?
            WHERE execution_mode = 'async' AND status = 'cancel_requested'
            """,
            (recovered_at, recovered_at),
        )
        conn.execute(
            """
            UPDATE agent_runs
            SET status = 'failed', final_answer = '服务重启导致任务中断，可从运行历史重新执行。',
                planner_mode = 'runtime_error', error_message = 'server_restarted',
                plan_json = '{"mode":"runtime_error","steps":[],"fallback_reason":"server_restarted","requested_model":null}',
                completed_at = ?, updated_at = ?
            WHERE execution_mode = 'async' AND status IN ('queued', 'running')
            """,
            (recovered_at, recovered_at),
        )


def runtime_error_result(exc: Exception) -> dict:
    return {
        "status": "failed",
        "final_answer": "Agent 运行异常，已记录失败状态。",
        "tool_calls": [],
        "plan": {
            "mode": "runtime_error",
            "steps": [],
            "fallback_reason": "unexpected_runtime_error",
            "requested_model": None,
        },
        "error_message": type(exc).__name__,
    }


def pending_plan() -> dict:
    return {
        "mode": "pending",
        "steps": [],
        "fallback_reason": None,
        "requested_model": None,
    }


def persist_agent_run(goal: str, result: dict, user: dict) -> int:
    run_id = create_agent_run(goal, user)
    finish_agent_run(run_id, result)
    return run_id


def serialize_hit(hit) -> dict:
    return {
        "document_id": hit.document_id,
        "document_title": hit.document_title,
        "document_filename": hit.document_filename,
        "chunk_index": hit.chunk_index,
        "score": round(hit.score, 4),
        "retrieval_mode": hit.retrieval_mode,
        "vector_backend": hit.vector_backend,
        "vector_degraded": hit.vector_degraded,
        "bm25_score": round(hit.bm25_score, 4),
        "vector_score": round(hit.vector_score, 4),
        "rerank_score": round(hit.rerank_score, 4),
    }


def tool_call(tool_name: str, tool_input: dict, status: str, output: dict, attempts: int = 1, duration_ms: float = 0) -> dict:
    return {
        "tool_name": tool_name,
        "input": tool_input,
        "status": status,
        "output": output,
        "attempts": attempts,
        "duration_ms": duration_ms,
    }


def failed_tool_call(tool_name: str, tool_input: dict, meta: dict) -> dict:
    return tool_call(
        tool_name,
        tool_input,
        "failed",
        {"error": meta["error"]},
        meta["attempts"],
        meta["duration_ms"],
    )


def failed_result(answer: str, calls: list[dict], plan: dict, error: str) -> dict:
    return {
        "status": "failed",
        "final_answer": answer,
        "tool_calls": calls,
        "plan": plan,
        "error_message": error,
    }


def clean_gap_question(goal: str) -> str:
    cleaned = goal.strip()
    for prefix in ("请创建知识缺口：", "创建知识缺口：", "请创建知识缺口:", "创建知识缺口:"):
        if cleaned.startswith(prefix):
            return cleaned[len(prefix) :].strip()
    return cleaned
