from dataclasses import dataclass, field


GATE_METRICS = (
    "recall_at_k",
    "mrr",
    "answer_accuracy",
    "abstention_accuracy",
    "access_control_accuracy",
)
DEFAULT_THRESHOLDS = {
    "recall_at_k": 0.80,
    "mrr": 0.75,
    "answer_accuracy": 0.80,
    "abstention_accuracy": 0.80,
    "access_control_accuracy": 1.0,
}
DEFAULT_MINIMUM_CASES = 10


@dataclass(frozen=True)
class QualityGatePolicy:
    thresholds: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    minimum_cases: int = DEFAULT_MINIMUM_CASES
    max_regression: float = 0.05

    def __post_init__(self) -> None:
        unknown = set(self.thresholds) - set(GATE_METRICS)
        if unknown:
            raise ValueError(f"不支持的质量门禁指标：{', '.join(sorted(unknown))}")
        if self.minimum_cases < 1:
            raise ValueError("minimum_cases 必须大于 0")
        if not 0 <= self.max_regression <= 1:
            raise ValueError("max_regression 必须在 0 到 1 之间")
        if any(not 0 <= float(value) <= 1 for value in self.thresholds.values()):
            raise ValueError("质量门禁阈值必须在 0 到 1 之间")


def summarize_evaluation_results(results: list[dict]) -> dict:
    total = len(results)
    if not total:
        raise ValueError("没有可汇总的评测结果")
    retrieval_results = [item for item in results if item.get("retrieval_recall") is not None]
    reciprocal_results = [item for item in results if item.get("reciprocal_rank") is not None]
    return {
        "total": total,
        "avg_score": _average(results, "score"),
        "avg_confidence": _average(results, "confidence"),
        "citation_hit_rate": _average(results, "citation_hit"),
        "recall_at_k": _average(retrieval_results, "retrieval_recall"),
        "mrr": _average(reciprocal_results, "reciprocal_rank"),
        "answer_accuracy": _average(results, "answer_correct"),
        "abstention_accuracy": _average(results, "abstention_correct"),
        "access_control_accuracy": _average(results, "access_control_correct"),
    }


def evaluate_quality_gate(
    summary: dict,
    policy: QualityGatePolicy | None = None,
    baseline: dict | None = None,
) -> dict:
    effective_policy = policy or QualityGatePolicy()
    checks = []
    failed_metrics: list[str] = []

    case_count = int(summary.get("total", 0))
    count_passed = case_count >= effective_policy.minimum_cases
    checks.append(
        {
            "metric": "total",
            "kind": "coverage",
            "actual": case_count,
            "required": effective_policy.minimum_cases,
            "passed": count_passed,
        }
    )
    if not count_passed:
        failed_metrics.append("total")

    for metric, threshold in effective_policy.thresholds.items():
        actual = float(summary.get(metric, 0.0))
        passed = actual >= threshold
        checks.append(
            {
                "metric": metric,
                "kind": "threshold",
                "actual": round(actual, 4),
                "required": round(float(threshold), 4),
                "passed": passed,
            }
        )
        if not passed:
            failed_metrics.append(metric)

    deltas = {}
    if baseline:
        for metric in GATE_METRICS:
            delta = float(summary.get(metric, 0.0)) - float(baseline.get(metric, 0.0))
            deltas[metric] = round(delta, 4)
            passed = delta >= -effective_policy.max_regression
            checks.append(
                {
                    "metric": metric,
                    "kind": "regression",
                    "actual": round(delta, 4),
                    "required": round(-effective_policy.max_regression, 4),
                    "passed": passed,
                }
            )
            if not passed and metric not in failed_metrics:
                failed_metrics.append(metric)

    return {
        "status": "passed" if not failed_metrics else "failed",
        "thresholds": {key: round(float(value), 4) for key, value in effective_policy.thresholds.items()},
        "minimum_cases": effective_policy.minimum_cases,
        "max_regression": round(effective_policy.max_regression, 4),
        "baseline_run_id": baseline.get("id") if baseline else None,
        "baseline_reference": baseline.get("reference", baseline.get("id")) if baseline else None,
        "metric_deltas": deltas,
        "failed_metrics": failed_metrics,
        "checks": checks,
    }


def rounded_summary(summary: dict) -> dict:
    return {
        key: value if key == "total" else round(float(value), 4)
        for key, value in summary.items()
    }


def _average(rows: list[dict], key: str) -> float:
    if not rows:
        return 0.0
    return sum(float(item.get(key) or 0.0) for item in rows) / len(rows)
