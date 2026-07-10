import json
import os
import time
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


def run_agent(goal: str, top_k: int, user: dict) -> dict:
    normalized_goal = goal.strip()
    plan = plan_agent(
        normalized_goal,
        can_manage_gaps=has_permission(user, "gaps.manage"),
        can_view_audit=has_permission(user, "audit.view"),
    )
    steps = list(plan.steps)
    tool_calls: list[dict] = []

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

    if confidence < 0.16 and TOOL_GAP not in steps:
        steps.append(TOOL_GAP)
    gap_id = None
    if TOOL_GAP in steps:
        gap_call, gap_id = create_gap_if_allowed(normalized_goal, user)
        tool_calls.append(gap_call)

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


def create_agent_run(goal: str, user: dict) -> int:
    started = utc_now()
    with get_conn() as conn:
        return conn.execute(
            """
            INSERT INTO agent_runs(
                goal, status, final_answer, user_id, tool_calls_json, plan_json,
                planner_mode, started_at, created_at
            )
            VALUES (?, 'running', '', ?, '[]', '{}', 'pending', ?, ?)
            """,
            (goal.strip(), user["id"], started, started),
        ).lastrowid


def finish_agent_run(run_id: int, result: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE agent_runs
            SET status = ?, final_answer = ?, tool_calls_json = ?, plan_json = ?,
                planner_mode = ?, error_message = ?, completed_at = ?
            WHERE id = ?
            """,
            (
                result["status"],
                result["final_answer"],
                json.dumps(result["tool_calls"], ensure_ascii=False),
                json.dumps(result["plan"], ensure_ascii=False),
                result["plan"]["mode"],
                result.get("error_message"),
                utc_now(),
                run_id,
            ),
        )


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
