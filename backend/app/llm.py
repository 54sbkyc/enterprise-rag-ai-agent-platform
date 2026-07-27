import os
from dataclasses import dataclass, field

from .provider_gateway import policy_from_env, post_json


@dataclass(frozen=True)
class LLMGeneration:
    answer: str | None
    model: str
    attempted: bool
    usage: dict[str, int] = field(default_factory=dict)
    fallback_reason: str | None = None
    provider_attempts: int = 0
    provider_latency_ms: int = 0
    provider_status_code: int | None = None


def generate_with_llm(question: str, citations: list[dict]) -> LLMGeneration:
    api_key = os.getenv("LLM_API_KEY", "").strip()
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("LLM_MODEL", "").strip()
    if not api_key or not model:
        return LLMGeneration(answer=None, model=model or "not-configured", attempted=False, fallback_reason="not_configured")

    context = "\n\n".join(
        f"[{index + 1}] {item['document_title']} #片段{item['chunk_index'] + 1}\n{item['content']}"
        for index, item in enumerate(citations[:5])
    )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是企业知识库问答助手。只能基于给定资料回答；如果资料不足，明确说明无法依据资料回答。回答要简洁，并保留来源编号。",
            },
            {
                "role": "user",
                "content": f"问题：{question}\n\n资料：\n{context}",
            },
        ],
        "temperature": 0.2,
    }
    response = post_json(
        f"{base_url}/chat/completions",
        payload=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        policy=policy_from_env("LLM", default_timeout_seconds=20, default_max_attempts=3),
    )
    if not response.ready:
        return LLMGeneration(
            answer=None,
            model=model,
            attempted=True,
            fallback_reason=response.error,
            provider_attempts=response.attempts,
            provider_latency_ms=response.latency_ms,
            provider_status_code=response.status_code,
        )

    try:
        data = response.payload or {}
        raw_answer = data["choices"][0]["message"]["content"]
        if not isinstance(raw_answer, str):
            raise ValueError("answer must be text")
        answer = raw_answer.strip()
        if not answer:
            raise ValueError("empty answer")
        raw_usage = data.get("usage") or {}
        if not isinstance(raw_usage, dict):
            raise ValueError("usage must be an object")
        usage = {
            "prompt_tokens": int(raw_usage.get("prompt_tokens") or 0),
            "completion_tokens": int(raw_usage.get("completion_tokens") or 0),
            "total_tokens": int(raw_usage.get("total_tokens") or 0),
        }
        return LLMGeneration(
            answer=answer,
            model=model,
            attempted=True,
            usage=usage,
            provider_attempts=response.attempts,
            provider_latency_ms=response.latency_ms,
            provider_status_code=response.status_code,
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return LLMGeneration(
            answer=None,
            model=model,
            attempted=True,
            fallback_reason="invalid_provider_response",
            provider_attempts=response.attempts,
            provider_latency_ms=response.latency_ms,
            provider_status_code=response.status_code,
        )
