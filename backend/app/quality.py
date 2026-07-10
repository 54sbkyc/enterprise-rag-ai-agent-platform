from dataclasses import dataclass


FEEDBACK_SCORES = {
    "helpful": 1.0,
    None: 0.6,
    "needs_info": 0.2,
    "unhelpful": 0.0,
}


@dataclass(frozen=True)
class QualityAssessment:
    confidence_score: float
    top_similarity_score: float
    citation_score: float
    feedback_score: float
    quality_score: float
    quality_level: str
    risk_reasons: list[str]


def calculate_quality(
    confidence: float,
    citation_scores: list[float],
    feedback_rating: str | None = None,
    blocked: bool = False,
) -> QualityAssessment:
    if blocked:
        return QualityAssessment(0.0, 0.0, 0.0, 0.0, 0.0, "blocked", ["问题被安全策略拦截"])

    confidence_score = max(0.0, min(float(confidence), 1.0))
    top_similarity_score = max(citation_scores, default=0.0)
    top_similarity_score = max(0.0, min(float(top_similarity_score), 1.0))
    citation_score = min(len(citation_scores) / 3, 1.0)
    feedback_score = FEEDBACK_SCORES.get(feedback_rating, FEEDBACK_SCORES[None])
    quality_score = (
        confidence_score * 0.45
        + top_similarity_score * 0.30
        + citation_score * 0.15
        + feedback_score * 0.10
    )

    if quality_score >= 0.75:
        quality_level = "passed"
    elif quality_score >= 0.55:
        quality_level = "watch"
    else:
        quality_level = "review"

    reasons = []
    if confidence_score < 0.45:
        reasons.append("置信度较低")
    if not citation_scores:
        reasons.append("缺少引用依据")
    elif top_similarity_score < 0.35:
        reasons.append("最高检索相似度较低")
    if feedback_rating == "unhelpful":
        reasons.append("员工反馈回答无用")
    elif feedback_rating == "needs_info":
        reasons.append("员工反馈需要补充资料")

    return QualityAssessment(
        confidence_score=confidence_score,
        top_similarity_score=top_similarity_score,
        citation_score=citation_score,
        feedback_score=feedback_score,
        quality_score=quality_score,
        quality_level=quality_level,
        risk_reasons=reasons,
    )
