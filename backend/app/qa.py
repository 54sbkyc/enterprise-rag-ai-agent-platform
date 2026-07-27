import os
import re

from .config import MIN_CONFIDENCE_FOR_ANSWER
from .llm import generate_with_llm
from .search import SearchHit
from .security import mask_sensitive
from .text_processing import split_sentences, tokenize


QUESTION_FILLERS = (
    "第一时间",
    "分别",
    "几个",
    "依次",
    "哪里",
    "从",
    "到",
    "具体",
    "公司",
    "普通",
    "外部",
    "最晚",
    "至少",
    "应该",
    "哪些",
    "什么",
    "要求",
    "方向",
    "能力",
    "遵守",
    "处理",
    "提交",
    "完成",
    "情况",
    "问题",
    "内容",
    "事项",
    "信息",
    "主要",
    "明确",
    "常见",
    "相关",
    "里面",
    "其中",
    "之后",
    "之前",
    "时候",
    "如果",
    "以及",
    "还有",
    "又要",
    "怎么做",
    "能不能",
    "最低",
    "最高",
    "的",
    "为什么",
    "请问",
    "需要",
    "可以",
    "是否",
    "如何",
    "怎么",
    "怎样",
    "多少",
    "多久",
    "哪些",
    "什么",
    "通过",
    "吗",
    "呢",
    "呀",
    "是",
    "由",
)
EVIDENCE_TERM_RE = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_]+")


def build_grounded_answer(question: str, hits: list[SearchHit]) -> tuple[str, float, list[dict], dict]:
    if not hits:
        return (
            "资料库中未检索到足够依据，无法给出可靠答案。",
            0.0,
            [],
            local_generation("no_retrieval_hits"),
        )

    citations = build_citations(hits)
    confidence = estimate_confidence(hits)
    evidence = assess_evidence_coverage(question, hits)
    minimum_coverage = max(
        _minimum_evidence_coverage(),
        0.7 if len(evidence["terms"]) <= 3 else 0.0,
    )
    if evidence["terms"] and (
        evidence["coverage"] < minimum_coverage
        or evidence["missing_hard_terms"]
    ):
        return (
            "资料库中未找到覆盖问题关键条件的明确依据。建议补充相关文档后再提问。",
            min(confidence, evidence["coverage"] * MIN_CONFIDENCE_FOR_ANSWER),
            [],
            local_generation(
                "insufficient_evidence_coverage",
                evidence_coverage=evidence["coverage"],
                missing_evidence_terms=list(
                    dict.fromkeys([*evidence["missing_hard_terms"], *evidence["missing_terms"]])
                ),
            ),
        )
    if confidence < MIN_CONFIDENCE_FOR_ANSWER:
        return (
            "资料库中未找到明确依据。建议补充相关文档后再提问。",
            confidence,
            [],
            local_generation(
                "low_confidence_guardrail",
                evidence_coverage=evidence["coverage"],
                missing_evidence_terms=evidence["missing_terms"],
            ),
        )

    llm_result = generate_with_llm(question, citations)
    if llm_result.answer:
        return (
            mask_sensitive(llm_result.answer),
            confidence,
            citations,
            {
                "mode": "llm",
                "model": llm_result.model,
                "requested_model": llm_result.model,
                "provider_usage": llm_result.usage,
                "fallback_reason": None,
                "provider_attempts": llm_result.provider_attempts,
                "provider_latency_ms": llm_result.provider_latency_ms,
                "provider_status_code": llm_result.provider_status_code,
                "prompt_version": llm_result.prompt_version,
            },
        )

    query_terms = set(tokenize(question))
    candidate_sentences: list[tuple[float, SearchHit, str]] = []
    for hit in hits:
        for sentence in split_sentences(hit.content):
            sentence_terms = set(tokenize(sentence))
            overlap = len(query_terms & sentence_terms)
            if overlap:
                score = hit.score + overlap / max(len(query_terms), 1)
                candidate_sentences.append((score, hit, sentence))

    if candidate_sentences:
        ranked_sentences = sorted(candidate_sentences, key=lambda item: item[0], reverse=True)
        best = _select_diverse_sentences(ranked_sentences, limit=6)
        answer = " ".join(sentence for _, _, sentence in best)
    else:
        answer = " ".join(hit.content[:220] for hit in hits[:2])

    generation = local_generation(llm_result.fallback_reason)
    if llm_result.attempted:
        generation.update(
            {
                "mode": "local_fallback",
                "requested_model": llm_result.model,
                "provider_attempts": llm_result.provider_attempts,
                "provider_latency_ms": llm_result.provider_latency_ms,
                "provider_status_code": llm_result.provider_status_code,
                "prompt_version": llm_result.prompt_version,
            }
        )
    return mask_sensitive(answer), confidence, citations, generation


def build_restricted_access_refusal() -> tuple[str, float, list[dict], dict]:
    return (
        "当前权限范围内未找到明确依据，无法给出可靠答案。",
        0.0,
        [],
        local_generation("restricted_access_scope"),
    )


def local_generation(
    reason: str | None = None,
    *,
    evidence_coverage: float | None = None,
    missing_evidence_terms: list[str] | None = None,
) -> dict:
    result = {
        "mode": "local_extractive",
        "model": "local-extractive",
        "requested_model": None,
        "provider_usage": {},
        "fallback_reason": reason,
        "provider_attempts": 0,
        "provider_latency_ms": 0,
        "provider_status_code": None,
        "prompt_version": "grounded-answer-v1",
    }
    if evidence_coverage is not None:
        result["evidence_coverage"] = round(evidence_coverage, 4)
        result["missing_evidence_terms"] = missing_evidence_terms or []
    return result


def assess_evidence_coverage(question: str, hits: list[SearchHit]) -> dict:
    terms = _evidence_terms(question)
    if not terms:
        return {
            "terms": [],
            "matched_terms": [],
            "missing_terms": [],
            "hard_terms": [],
            "missing_hard_terms": [],
            "coverage": 1.0,
        }
    evidence_text = " ".join(f"{hit.document_title} {hit.content}" for hit in hits).lower()
    matched = [term for term in terms if term in evidence_text]
    missing = [term for term in terms if term not in evidence_text]
    hard_terms = list(dict.fromkeys(re.findall(r"\d+(?:\.\d+)?", question.lower())))
    missing_hard_terms = [term for term in hard_terms if term not in evidence_text]
    return {
        "terms": terms,
        "matched_terms": matched,
        "missing_terms": missing,
        "hard_terms": hard_terms,
        "missing_hard_terms": missing_hard_terms,
        "coverage": len(matched) / len(terms),
    }


def _select_diverse_sentences(
    candidates: list[tuple[float, SearchHit, str]], limit: int
) -> list[tuple[float, SearchHit, str]]:
    selected: list[tuple[float, SearchHit, str]] = []
    per_document: dict[int, int] = {}
    for candidate in candidates:
        document_id = candidate[1].document_id
        if per_document.get(document_id, 0) >= 2:
            continue
        selected.append(candidate)
        per_document[document_id] = per_document.get(document_id, 0) + 1
        if len(selected) == limit:
            break
    return selected


def _evidence_terms(question: str) -> list[str]:
    reduced = question.lower()
    for filler in QUESTION_FILLERS:
        reduced = reduced.replace(filler, " ")
    terms: list[str] = []
    for segment in EVIDENCE_TERM_RE.findall(reduced):
        if re.fullmatch(r"[\u4e00-\u9fff]+", segment):
            terms.extend(_tokenize_evidence_segment(segment))
        else:
            terms.append(segment)
    return list(dict.fromkeys(terms))


def _tokenize_evidence_segment(segment: str) -> list[str]:
    try:
        import jieba

        tokens = [token.strip() for token in jieba.lcut(segment) if len(token.strip()) >= 2]
        if tokens:
            return tokens
    except ImportError:
        pass
    if len(segment) == 2:
        return [segment]
    return [segment[index : index + 2] for index in range(len(segment) - 1)]


def _minimum_evidence_coverage() -> float:
    try:
        value = float(os.getenv("RAG_MIN_EVIDENCE_COVERAGE", "0.5"))
    except ValueError:
        return 0.5
    return min(1.0, max(0.0, value))


def build_citations(hits: list[SearchHit]) -> list[dict]:
    return [
        {
            "document_id": hit.document_id,
            "document_title": hit.document_title,
            "document_filename": hit.document_filename,
            "document_access_level": hit.document_access_level,
            "chunk_id": hit.chunk_id,
            "chunk_index": hit.chunk_index,
            "score": round(hit.score, 4),
            "retrieval_mode": hit.retrieval_mode,
            "vector_backend": hit.vector_backend,
            "vector_degraded": hit.vector_degraded,
            "lexical_backend": hit.lexical_backend,
            "lexical_degraded": hit.lexical_degraded,
            "candidate_count": hit.candidate_count,
            "corpus_count": hit.corpus_count,
            "score_breakdown": {
                "bm25": round(hit.bm25_score, 4),
                "vector": round(hit.vector_score, 4),
                "rerank": round(hit.rerank_score, 4),
                "final": round(hit.score, 4),
            },
            "content": mask_sensitive(hit.content[:520]),
        }
        for hit in hits
    ]


def estimate_confidence(hits: list[SearchHit]) -> float:
    if not hits:
        return 0.0
    return min(0.98, sum(hit.score for hit in hits[:3]) / min(len(hits), 3) + 0.18)
