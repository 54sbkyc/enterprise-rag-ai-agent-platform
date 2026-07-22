import hashlib
import json
from pathlib import Path


DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "golden_cases.v1.json"
DEFAULT_BASELINE_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "approved_baseline.v1.json"
BASELINE_METRICS = ("recall_at_k", "mrr", "answer_accuracy", "abstention_accuracy")


class EvaluationDatasetError(ValueError):
    pass


def load_evaluation_dataset(path: Path | None = None) -> dict:
    dataset_path = path or DEFAULT_DATASET_PATH
    try:
        payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationDatasetError(f"无法读取评测数据集：{dataset_path}") from exc

    version = str(payload.get("version", "")).strip()
    raw_cases = payload.get("cases")
    if not version or not isinstance(raw_cases, list) or not raw_cases:
        raise EvaluationDatasetError("评测数据集必须包含版本号和至少一个用例")

    normalized_cases = []
    seen_keys: set[str] = set()
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise EvaluationDatasetError(f"第 {index} 个评测用例格式无效")
        case_key = str(raw_case.get("key", "")).strip()
        question = str(raw_case.get("question", "")).strip()
        if not case_key or not question:
            raise EvaluationDatasetError(f"第 {index} 个评测用例缺少 key 或 question")
        if case_key in seen_keys:
            raise EvaluationDatasetError(f"评测用例 key 重复：{case_key}")
        seen_keys.add(case_key)
        normalized_cases.append(
            {
                "key": case_key,
                "category": str(raw_case.get("category", "general")).strip() or "general",
                "question": question,
                "expected_keywords": _string_list(raw_case.get("expected_keywords"), index, "expected_keywords"),
                "expected_documents": _string_list(raw_case.get("expected_documents"), index, "expected_documents"),
                "should_answer": bool(raw_case.get("should_answer", True)),
            }
        )

    return {
        "version": version,
        "description": str(payload.get("description", "")).strip(),
        "cases": normalized_cases,
        "fingerprint": dataset_fingerprint(version, normalized_cases),
        "path": str(dataset_path),
    }


def load_evaluation_baseline(path: Path | None = None) -> dict:
    baseline_path = path or DEFAULT_BASELINE_PATH
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationDatasetError(f"无法读取批准基线：{baseline_path}") from exc

    version = str(payload.get("version", "")).strip()
    dataset_version = str(payload.get("dataset_version", "")).strip()
    dataset_fingerprint_value = str(payload.get("dataset_fingerprint", "")).strip().lower()
    top_k = payload.get("top_k")
    raw_metrics = payload.get("metrics")
    if not version or not dataset_version or not _is_sha256(dataset_fingerprint_value):
        raise EvaluationDatasetError("批准基线缺少有效的版本、数据集版本或 SHA-256 指纹")
    if not isinstance(top_k, int) or not 1 <= top_k <= 10:
        raise EvaluationDatasetError("批准基线的 top_k 必须在 1 到 10 之间")
    if not isinstance(raw_metrics, dict) or set(raw_metrics) != set(BASELINE_METRICS):
        raise EvaluationDatasetError("批准基线必须包含完整的四项门禁指标")
    metrics = {}
    for metric in BASELINE_METRICS:
        try:
            value = float(raw_metrics[metric])
        except (TypeError, ValueError) as exc:
            raise EvaluationDatasetError(f"批准基线指标无效：{metric}") from exc
        if not 0 <= value <= 1:
            raise EvaluationDatasetError(f"批准基线指标必须在 0 到 1 之间：{metric}")
        metrics[metric] = value

    return {
        "version": version,
        "dataset_version": dataset_version,
        "dataset_fingerprint": dataset_fingerprint_value,
        "top_k": top_k,
        "metrics": metrics,
        "path": str(baseline_path),
    }


def dataset_fingerprint(version: str, cases: list[dict]) -> str:
    canonical = json.dumps(
        {"version": version, "cases": cases},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cases_fingerprint(cases: list[dict]) -> str:
    versions = sorted({str(item.get("dataset_version") or "custom") for item in cases})
    version = versions[0] if len(versions) == 1 else "+".join(versions)
    normalized = [
        {
            "key": str(item.get("case_key") or f"custom-{item.get('id', index)}"),
            "category": str(item.get("category") or "general"),
            "question": str(item["question"]),
            "expected_keywords": list(item.get("expected_keywords") or []),
            "expected_documents": list(item.get("expected_documents") or []),
            "should_answer": bool(item.get("should_answer", True)),
        }
        for index, item in enumerate(cases, start=1)
    ]
    return dataset_fingerprint(version, normalized)


def _string_list(value, case_index: int, field: str) -> list[str]:
    if not isinstance(value, list):
        raise EvaluationDatasetError(f"第 {case_index} 个评测用例的 {field} 必须是数组")
    result = [str(item).strip().lower() for item in value if str(item).strip()]
    if len(result) != len(value):
        raise EvaluationDatasetError(f"第 {case_index} 个评测用例的 {field} 包含空值")
    return result


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
