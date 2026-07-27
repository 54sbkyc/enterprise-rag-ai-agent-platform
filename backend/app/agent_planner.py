import json
import os
from dataclasses import dataclass

from .provider_gateway import policy_from_env, post_json


TOOL_SECURITY = "security_check"
TOOL_SEARCH = "search_knowledge_base"
TOOL_ANSWER = "generate_grounded_answer"
TOOL_GAP = "create_knowledge_gap"
TOOL_LOGS = "query_recent_logs"
ALLOWED_TOOLS = {TOOL_SECURITY, TOOL_SEARCH, TOOL_ANSWER, TOOL_GAP, TOOL_LOGS}

GAP_KEYWORDS = ("知识缺口", "补充资料", "创建缺口", "无法回答", "没有收录")
LOG_KEYWORDS = ("日志", "历史问答", "最近问答", "问答记录")


@dataclass(frozen=True)
class AgentPlan:
    mode: str
    steps: list[str]
    fallback_reason: str | None = None
    requested_model: str | None = None
    provider_attempts: int = 0
    provider_latency_ms: int = 0
    provider_status_code: int | None = None

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "steps": self.steps,
            "fallback_reason": self.fallback_reason,
            "requested_model": self.requested_model,
            "provider_attempts": self.provider_attempts,
            "provider_latency_ms": self.provider_latency_ms,
            "provider_status_code": self.provider_status_code,
        }


def plan_agent(goal: str, *, can_manage_gaps: bool, can_view_audit: bool) -> AgentPlan:
    fallback = deterministic_plan(goal)
    if os.getenv("AGENT_PLANNER_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return fallback

    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("AGENT_PLANNER_MODEL", os.getenv("LLM_MODEL", "")).strip()
    if not api_key or not model:
        return AgentPlan(
            mode="deterministic",
            steps=fallback.steps,
            fallback_reason="planner_not_configured",
            requested_model=model or None,
        )

    requested, error, telemetry = _request_model_plan(goal, model, api_key, can_manage_gaps, can_view_audit)
    if error:
        return AgentPlan(
            mode="deterministic",
            steps=fallback.steps,
            fallback_reason=error,
            requested_model=model,
            **telemetry,
        )
    validated, validation_error = validate_tool_steps(
        requested,
        fallback.steps,
        can_manage_gaps=can_manage_gaps,
        can_view_audit=can_view_audit,
    )
    if validation_error:
        return AgentPlan(
            mode="deterministic",
            steps=validated,
            fallback_reason=validation_error,
            requested_model=model,
            **telemetry,
        )
    return AgentPlan(mode="llm", steps=validated, requested_model=model, **telemetry)


def deterministic_plan(goal: str) -> AgentPlan:
    if any(keyword in goal for keyword in LOG_KEYWORDS):
        return AgentPlan("deterministic", [TOOL_SECURITY, TOOL_LOGS])
    steps = [TOOL_SECURITY, TOOL_SEARCH, TOOL_ANSWER]
    if any(keyword in goal for keyword in GAP_KEYWORDS):
        steps.append(TOOL_GAP)
    return AgentPlan("deterministic", steps)


def validate_tool_steps(
    requested: list[str],
    fallback_steps: list[str],
    *,
    can_manage_gaps: bool,
    can_view_audit: bool,
) -> tuple[list[str], str | None]:
    if not isinstance(requested, list) or not requested or len(requested) > 5:
        return list(fallback_steps), "invalid_tool_plan"
    if any(not isinstance(step, str) or step not in ALLOWED_TOOLS for step in requested):
        return list(fallback_steps), "invalid_tool_plan"

    steps = list(dict.fromkeys(requested))
    if steps[0] != TOOL_SECURITY:
        steps.insert(0, TOOL_SECURITY)
    if TOOL_LOGS in steps:
        if any(step in steps for step in (TOOL_SEARCH, TOOL_ANSWER, TOOL_GAP)):
            return list(fallback_steps), "invalid_tool_plan"
        return [TOOL_SECURITY, TOOL_LOGS], None
    if TOOL_SEARCH not in steps or TOOL_ANSWER not in steps:
        return list(fallback_steps), "invalid_tool_plan"
    if steps.index(TOOL_SEARCH) > steps.index(TOOL_ANSWER):
        return list(fallback_steps), "invalid_tool_plan"
    ordered = [TOOL_SECURITY, TOOL_SEARCH, TOOL_ANSWER]
    if TOOL_GAP in steps:
        ordered.append(TOOL_GAP)
    return ordered, None


def _request_model_plan(
    goal: str,
    model: str,
    api_key: str,
    can_manage_gaps: bool,
    can_view_audit: bool,
) -> tuple[list[str], str | None, dict]:
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是企业知识库 Agent 规划器。只返回 JSON：{\"tools\":[工具名]}。"
                    "可用工具仅有 security_check、search_knowledge_base、generate_grounded_answer、"
                    "create_knowledge_gap、query_recent_logs。security_check 必须第一步；"
                    "search 必须在 answer 前；日志查询不能和知识检索混用。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"目标：{goal}\n"
                    f"可管理知识缺口：{can_manage_gaps}\n"
                    f"可查看审计日志：{can_view_audit}"
                ),
            },
        ],
        "temperature": 0,
    }
    response = post_json(
        f"{base_url}/chat/completions",
        payload=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        policy=policy_from_env("AGENT_PLANNER", default_timeout_seconds=15, default_max_attempts=2),
    )
    telemetry = {
        "provider_attempts": response.attempts,
        "provider_latency_ms": response.latency_ms,
        "provider_status_code": response.status_code,
    }
    if not response.ready:
        return [], response.error or "planner_unavailable", telemetry
    try:
        data = response.payload or {}
        content = str(data["choices"][0]["message"]["content"]).strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:].strip()
        tools = json.loads(content)["tools"]
        return tools, None, telemetry
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return [], "invalid_planner_response", telemetry
