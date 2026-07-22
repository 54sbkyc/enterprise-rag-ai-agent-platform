import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the deterministic enterprise RAG quality gate.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--minimum-cases", type=int, default=5)
    parser.add_argument("--max-regression", type=float, default=0.05)
    parser.add_argument("--min-recall", type=float, default=0.80)
    parser.add_argument("--min-mrr", type=float, default=0.75)
    parser.add_argument("--min-answer-accuracy", type=float, default=0.80)
    parser.add_argument("--min-abstention-accuracy", type=float, default=0.80)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline", type=Path, help="Use a specific approved baseline JSON file.")
    parser.add_argument(
        "--no-baseline",
        action="store_true",
        help="Run absolute thresholds only. Required when intentionally changing the dataset or Top K.",
    )
    parser.add_argument(
        "--allow-remote-providers",
        action="store_true",
        help="Allow configured LLM and embedding providers. The default is deterministic local evaluation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _validate_args(args)
    with tempfile.TemporaryDirectory(prefix="enterprise-rag-eval-") as temp_dir:
        runtime = Path(temp_dir)
        os.environ["RAG_DB_PATH"] = str(runtime / "quality-gate.db")
        os.environ["RAG_UPLOAD_DIR"] = str(runtime / "uploads")
        if not args.allow_remote_providers:
            for name in ("LLM_API_KEY", "LLM_MODEL", "EMBEDDING_API_KEY", "EMBEDDING_MODEL"):
                os.environ.pop(name, None)

        from app.db import get_conn
        from app.evaluation_dataset import load_evaluation_baseline
        from app.evaluation_gate import QualityGatePolicy, evaluate_quality_gate
        from app.main import BatchEvaluateRequest, EvaluationThresholds, run_batch_evaluation
        from seed_enterprise_documents import seed_documents

        seed_documents()
        with get_conn() as conn:
            admin = conn.execute(
                "SELECT id, username, role, display_name, is_active FROM users WHERE username = 'admin'"
            ).fetchone()
        if not admin:
            raise RuntimeError("quality gate admin user was not seeded")

        result = run_batch_evaluation(
            BatchEvaluateRequest(
                top_k=args.top_k,
                use_baseline=False,
                minimum_cases=args.minimum_cases,
                max_regression=args.max_regression,
                thresholds=EvaluationThresholds(
                    recall_at_k=args.min_recall,
                    mrr=args.min_mrr,
                    answer_accuracy=args.min_answer_accuracy,
                    abstention_accuracy=args.min_abstention_accuracy,
                ),
            ),
            dict(admin),
        )

        if not args.no_baseline:
            baseline = load_evaluation_baseline(args.baseline)
            _validate_baseline(baseline, result["dataset"])
            result["gate"] = evaluate_quality_gate(
                result["summary"],
                QualityGatePolicy(
                    thresholds=result["gate"]["thresholds"],
                    minimum_cases=args.minimum_cases,
                    max_regression=args.max_regression,
                ),
                {"id": None, "reference": baseline["version"], **baseline["metrics"]},
            )
            result["dataset"]["approved_baseline"] = baseline["version"]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": result["dataset"],
        "summary": result["summary"],
        "gate": result["gate"],
        "failed_cases": [
            {
                "case_key": item.get("case_key"),
                "question": item["question"],
                "answer_correct": item["answer_correct"],
                "abstention_correct": item["abstention_correct"],
                "retrieval_recall": item["retrieval_recall"],
                "reciprocal_rank": item["reciprocal_rank"],
            }
            for item in result["results"]
            if not item["answer_correct"] or not item["abstention_correct"]
        ],
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    _print_report(report)
    return 0 if report["gate"]["status"] == "passed" else 1


def _validate_args(args: argparse.Namespace) -> None:
    if args.no_baseline and args.baseline:
        raise SystemExit("--baseline and --no-baseline cannot be used together")
    if not 1 <= args.top_k <= 10:
        raise SystemExit("--top-k must be between 1 and 10")
    if args.minimum_cases < 1:
        raise SystemExit("--minimum-cases must be greater than 0")
    for name in (
        "max_regression",
        "min_recall",
        "min_mrr",
        "min_answer_accuracy",
        "min_abstention_accuracy",
    ):
        value = getattr(args, name)
        if not 0 <= value <= 1:
            raise SystemExit(f"--{name.replace('_', '-')} must be between 0 and 1")


def _validate_baseline(baseline: dict, dataset: dict) -> None:
    if baseline["dataset_version"] != dataset["version"]:
        raise SystemExit("approved baseline dataset version does not match the golden dataset")
    if baseline["dataset_fingerprint"] != dataset["fingerprint"]:
        raise SystemExit("approved baseline fingerprint does not match the golden dataset")
    if baseline["top_k"] != dataset["top_k"]:
        raise SystemExit("approved baseline Top K does not match this run; use --no-baseline intentionally")


def _print_report(report: dict) -> None:
    summary = report["summary"]
    gate = report["gate"]
    print(f"RAG quality gate: {gate['status'].upper()}")
    print(f"Dataset: {report['dataset']['version']} ({report['dataset']['fingerprint'][:12]})")
    print(f"Cases: {summary['total']}")
    print(f"Recall@K: {summary['recall_at_k']:.2%}")
    print(f"MRR: {summary['mrr']:.4f}")
    print(f"Answer accuracy: {summary['answer_accuracy']:.2%}")
    print(f"Abstention accuracy: {summary['abstention_accuracy']:.2%}")
    if gate.get("baseline_reference"):
        print(f"Approved baseline: {gate['baseline_reference']}")
    if gate["failed_metrics"]:
        print(f"Failed metrics: {', '.join(gate['failed_metrics'])}")


if __name__ == "__main__":
    raise SystemExit(main())
