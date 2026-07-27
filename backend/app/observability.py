import math
import os


def estimate_token_count(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, math.ceil(len(stripped) / 4))


def build_usage_summary(question: str, citations: list[dict], answer: str, generation: dict | None = None) -> dict:
    context = "\n".join(item.get("content", "") for item in citations[:5])
    estimated_prompt_tokens = estimate_token_count(f"{question}\n{context}")
    estimated_completion_tokens = estimate_token_count(answer)
    generation = generation or {
        "mode": "local_extractive",
        "model": "local-extractive",
        "requested_model": None,
        "provider_usage": {},
        "fallback_reason": None,
        "provider_attempts": 0,
        "provider_latency_ms": 0,
        "provider_status_code": None,
        "prompt_version": "grounded-answer-v1",
    }
    provider_usage = generation.get("provider_usage") or {}
    token_source = "provider" if generation.get("mode") == "llm" and provider_usage else "estimated"
    prompt_tokens = int(provider_usage.get("prompt_tokens") or estimated_prompt_tokens)
    completion_tokens = int(provider_usage.get("completion_tokens") or estimated_completion_tokens)
    total_tokens = int(provider_usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    input_cost = _env_float("LLM_INPUT_COST_PER_1K")
    output_cost = _env_float("LLM_OUTPUT_COST_PER_1K")
    estimated_cost = (prompt_tokens / 1000 * input_cost) + (completion_tokens / 1000 * output_cost)
    llm_configured = bool(os.getenv("LLM_API_KEY", "").strip() and os.getenv("LLM_MODEL", "").strip())

    return {
        "model": generation.get("model") or "local-extractive",
        "requested_model": generation.get("requested_model"),
        "generation_mode": generation.get("mode", "local_extractive"),
        "fallback_reason": generation.get("fallback_reason"),
        "provider_attempts": int(generation.get("provider_attempts") or 0),
        "provider_latency_ms": int(generation.get("provider_latency_ms") or 0),
        "provider_status_code": generation.get("provider_status_code"),
        "prompt_version": generation.get("prompt_version") or "grounded-answer-v1",
        "evidence_coverage": generation.get("evidence_coverage"),
        "missing_evidence_terms": generation.get("missing_evidence_terms") or [],
        "token_source": token_source,
        "llm_configured": llm_configured,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": round(estimated_cost, 6),
        "pricing": {
            "input_per_1k": input_cost,
            "output_per_1k": output_cost,
            "source": "env" if input_cost or output_cost else "not_configured",
        },
    }


def build_agent_trace(
    *,
    security_allowed: bool,
    block_reason: str | None,
    access_levels: list[str],
    hit_count: int,
    top_score: float,
    confidence: float,
    answer: str,
    usage: dict,
) -> list[dict]:
    trace = [
        {
            "stage": "security_check",
            "status": "passed" if security_allowed else "blocked",
            "detail": "未命中 Prompt 注入或越权查询规则" if security_allowed else block_reason,
            "metrics": {"blocked": not security_allowed},
        }
    ]
    if not security_allowed:
        return trace

    trace.extend(
        [
            {
                "stage": "permission_scope",
                "status": "completed",
                "detail": "按当前用户角色限定可检索文档密级",
                "metrics": {"access_levels": access_levels},
            },
            {
                "stage": "retrieval",
                "status": "completed" if hit_count else "empty",
                "detail": "完成权限过滤后的知识片段检索",
                "metrics": {
                    "hit_count": hit_count,
                    "top_score": round(top_score, 4),
                    "confidence": round(confidence, 4),
                },
            },
            {
                "stage": "answer_generation",
                "status": "completed",
                "detail": generation_detail(usage),
                "metrics": {
                    "model": usage["model"],
                    "requested_model": usage.get("requested_model"),
                    "generation_mode": usage.get("generation_mode"),
                    "fallback_reason": usage.get("fallback_reason"),
                    "provider_attempts": usage.get("provider_attempts", 0),
                    "provider_latency_ms": usage.get("provider_latency_ms", 0),
                    "provider_status_code": usage.get("provider_status_code"),
                    "prompt_version": usage.get("prompt_version"),
                    "evidence_coverage": usage.get("evidence_coverage"),
                    "missing_evidence_terms": usage.get("missing_evidence_terms") or [],
                    "token_source": usage.get("token_source"),
                    "llm_configured": usage["llm_configured"],
                    "answer_chars": len(answer),
                    "total_tokens": usage["total_tokens"],
                },
            },
        ]
    )
    return trace


def generation_detail(usage: dict) -> str:
    mode = usage.get("generation_mode")
    if mode == "llm":
        return "大模型基于权限过滤后的引用资料生成回答"
    if mode == "local_fallback":
        return "大模型调用未成功，已自动降级为本地抽取式回答"
    if mode == "blocked":
        return "安全策略已阻止回答生成"
    if usage.get("fallback_reason") == "insufficient_evidence_coverage":
        return "问题中的关键条件未被检索依据覆盖，系统已执行保守拒答"
    return "使用本地抽取式生成可信回答"


def _env_float(name: str) -> float:
    try:
        return float(os.getenv(name, "0") or 0)
    except ValueError:
        return 0.0
