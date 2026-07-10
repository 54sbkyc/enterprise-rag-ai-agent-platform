import pytest

from app.quality import calculate_quality


def test_quality_score_uses_documented_weights():
    result = calculate_quality(
        confidence=0.8,
        citation_scores=[0.7, 0.4, 0.2],
        feedback_rating="helpful",
    )

    assert result.quality_score == pytest.approx(0.8 * 0.45 + 0.7 * 0.30 + 1.0 * 0.15 + 1.0 * 0.10)
    assert result.quality_level == "passed"


def test_low_quality_answer_requires_review():
    result = calculate_quality(
        confidence=0.2,
        citation_scores=[],
        feedback_rating="unhelpful",
    )

    assert result.quality_level == "review"
    assert "置信度较低" in result.risk_reasons
    assert "缺少引用依据" in result.risk_reasons
    assert "员工反馈回答无用" in result.risk_reasons


def test_blocked_question_is_not_scored_as_knowledge_gap():
    result = calculate_quality(
        confidence=0,
        citation_scores=[],
        blocked=True,
    )

    assert result.quality_level == "blocked"
    assert result.quality_score == 0
