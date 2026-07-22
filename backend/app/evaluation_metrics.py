from dataclasses import dataclass


REFUSAL_MARKERS = (
    "无法给出可靠答案",
    "未找到明确依据",
    "未找到覆盖问题关键条件的明确依据",
    "未检索到足够依据",
    "资料不足",
    "无法依据资料回答",
)


@dataclass(frozen=True)
class CaseSignals:
    retrieval_recall: float | None
    reciprocal_rank: float | None
    answer_correct: int
    abstention_correct: int
    access_control_correct: int
    refused: bool


def retrieval_recall(citations: list[dict], expected_documents: list[str]) -> float | None:
    expected = _normalized(expected_documents)
    if not expected:
        return None
    names = _citation_names(citations)
    hits = sum(1 for document in expected if any(document in name for name in names))
    return hits / len(expected)


def reciprocal_rank(citations: list[dict], expected_documents: list[str]) -> float | None:
    expected = _normalized(expected_documents)
    if not expected:
        return None
    for rank, item in enumerate(citations, start=1):
        names = _citation_names([item])
        if any(document in name for document in expected for name in names):
            return 1.0 / rank
    return 0.0


def evaluate_case_signals(
    *,
    answer: str,
    confidence: float,
    citations: list[dict],
    expected_keywords: list[str],
    expected_documents: list[str],
    should_answer: bool,
    allowed_access_levels: list[str],
) -> CaseSignals:
    refused = is_refusal(answer, confidence, citations)
    if should_answer:
        keywords = _normalized(expected_keywords)
        lowered_answer = answer.lower()
        keyword_hit_rate = (
            sum(1 for keyword in keywords if keyword in lowered_answer) / len(keywords)
            if keywords
            else (0.0 if refused else 1.0)
        )
        answer_correct = int(not refused and keyword_hit_rate >= 0.5)
    else:
        answer_correct = int(refused)
    return CaseSignals(
        retrieval_recall=retrieval_recall(citations, expected_documents),
        reciprocal_rank=reciprocal_rank(citations, expected_documents),
        answer_correct=answer_correct,
        abstention_correct=int(refused == (not should_answer)),
        access_control_correct=int(
            all(item.get("document_access_level") in allowed_access_levels for item in citations)
        ),
        refused=refused,
    )


def is_refusal(answer: str, confidence: float, citations: list[dict]) -> bool:
    if any(marker in answer for marker in REFUSAL_MARKERS):
        return True
    return confidence <= 0.05 and not citations


def _normalized(values) -> list[str]:
    return [str(value).strip().lower() for value in values if str(value).strip()]


def _citation_names(citations: list[dict]) -> list[str]:
    return [
        " ".join(
            (
                str(item.get("document_title", "")).strip().lower(),
                str(item.get("document_filename", "")).strip().lower(),
            )
        )
        for item in citations
    ]
