import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LLMGeneration:
    answer: str | None
    model: str
    attempted: bool
    usage: dict[str, int] = field(default_factory=dict)
    fallback_reason: str | None = None


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
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        answer = data["choices"][0]["message"]["content"].strip()
        if not answer:
            raise ValueError("empty answer")
        raw_usage = data.get("usage") or {}
        usage = {
            "prompt_tokens": int(raw_usage.get("prompt_tokens") or 0),
            "completion_tokens": int(raw_usage.get("completion_tokens") or 0),
            "total_tokens": int(raw_usage.get("total_tokens") or 0),
        }
        return LLMGeneration(answer=answer, model=model, attempted=True, usage=usage)
    except urllib.error.URLError:
        return LLMGeneration(
            answer=None,
            model=model,
            attempted=True,
            fallback_reason="provider_unavailable",
        )
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return LLMGeneration(
            answer=None,
            model=model,
            attempted=True,
            fallback_reason="invalid_provider_response",
        )
