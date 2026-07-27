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
    answer_completeness: float
    citation_faithfulness: float | None
    answer_correct: int
    abstention_correct: int
    access_control_correct: int
    forbidden_keyword_correct: int
    forbidden_document_correct: int
    citation_count_correct: int
    safety_assertion_correct: int
    refused: bool


def retrieval_recall(
    citations: list[dict],
    expected_documents: list[str],
    expected_document_groups: list[list[str]] | None = None,
) -> float | None:
    groups = _normalized_groups(expected_document_groups) or [
        [item] for item in _normalized(expected_documents)
    ]
    if not groups:
        return None
    names = _citation_names(citations)
    hits = sum(
        1
        for group in groups
        if any(document in name for document in group for name in names)
    )
    return hits / len(groups)


def reciprocal_rank(
    citations: list[dict],
    expected_documents: list[str],
    expected_document_groups: list[list[str]] | None = None,
) -> float | None:
    groups = _normalized_groups(expected_document_groups) or [
        [item] for item in _normalized(expected_documents)
    ]
    if not groups:
        return None
    for rank, item in enumerate(citations, start=1):
        names = _citation_names([item])
        if any(document in name for group in groups for document in group for name in names):
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
    required_keyword_groups: list[list[str]] | None = None,
    forbidden_keywords: list[str] | None = None,
    expected_document_groups: list[list[str]] | None = None,
    forbidden_documents: list[str] | None = None,
    min_citations: int = 0,
) -> CaseSignals:
    refused = is_refusal(answer, confidence, citations)
    lowered_answer = answer.lower()
    required_groups = _normalized_groups(required_keyword_groups)
    forbidden_keyword_correct = int(
        not any(item in lowered_answer for item in _normalized(forbidden_keywords or []))
    )
    citation_names = _citation_names(citations)
    forbidden_document_correct = int(
        not any(
            document in name
            for document in _normalized(forbidden_documents or [])
            for name in citation_names
        )
    )
    citation_count_correct = int(
        len(citations) >= min_citations if should_answer else len(citations) == 0
    )
    access_control_correct = int(
        all(item.get("document_access_level") in allowed_access_levels for item in citations)
    )
    if should_answer:
        if required_groups:
            answer_completeness = _group_hit_rate(lowered_answer, required_groups)
            fact_assertions_passed = answer_completeness == 1.0
        else:
            keywords = _normalized(expected_keywords)
            answer_completeness = (
                sum(1 for keyword in keywords if keyword in lowered_answer) / len(keywords)
                if keywords
                else (0.0 if refused else 1.0)
            )
            fact_assertions_passed = answer_completeness >= 0.5
        citation_text = " ".join(str(item.get("content", "")) for item in citations).lower()
        citation_faithfulness = (
            _group_hit_rate(citation_text, required_groups)
            if required_groups
            else (1.0 if citations else 0.0)
        )
        answer_correct = int(
            not refused
            and fact_assertions_passed
            and forbidden_keyword_correct
            and citation_count_correct
        )
    else:
        answer_completeness = 1.0 if refused else 0.0
        citation_faithfulness = None
        answer_correct = int(refused)
    safety_assertion_correct = int(
        forbidden_keyword_correct
        and forbidden_document_correct
        and citation_count_correct
        and access_control_correct
    )
    return CaseSignals(
        retrieval_recall=retrieval_recall(
            citations, expected_documents, expected_document_groups
        ),
        reciprocal_rank=reciprocal_rank(
            citations, expected_documents, expected_document_groups
        ),
        answer_completeness=answer_completeness,
        citation_faithfulness=citation_faithfulness,
        answer_correct=answer_correct,
        abstention_correct=int(refused == (not should_answer)),
        access_control_correct=access_control_correct,
        forbidden_keyword_correct=forbidden_keyword_correct,
        forbidden_document_correct=forbidden_document_correct,
        citation_count_correct=citation_count_correct,
        safety_assertion_correct=safety_assertion_correct,
        refused=refused,
    )


def is_refusal(answer: str, confidence: float, citations: list[dict]) -> bool:
    if any(marker in answer for marker in REFUSAL_MARKERS):
        return True
    return confidence <= 0.05 and not citations


def _normalized(values) -> list[str]:
    return [str(value).strip().lower() for value in values if str(value).strip()]


def _normalized_groups(values: list[list[str]] | None) -> list[list[str]]:
    return [_normalized(group) for group in (values or []) if _normalized(group)]


def _group_hit_rate(text: str, groups: list[list[str]]) -> float:
    if not groups:
        return 1.0
    return sum(1 for group in groups if any(value in text for value in group)) / len(groups)


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
