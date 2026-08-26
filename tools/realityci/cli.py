"""RealityCI command-line entry points.

Every command performs real work and writes real artifacts under the
caller-supplied output directory: deterministic scenario pools, labeled
datasets, actual PyTorch training, and measured evaluation matrices.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.realityci.evaluate import evaluate_suite, report_summary_line
from tools.realityci.policy.torch_perception import (
    INPUT_SPEC,
    TorchOcclusionPerceptionAdapter,
    save_checkpoint_file,
)
from tools.realityci.pools import build_clear_pool, build_occluded_pool
from tools.realityci.trainers import (
    TorchBehaviorCloningTrainer,
    TrainingRequest,
    build_dataset,
)
from tools.realityci.schemas.training import TrainingLimits


def _dataset_summary(dataset) -> dict:
    return {
        "samples": len(dataset),
        "positives": dataset.positive_count,
        "negatives": len(dataset) - dataset.positive_count,
    }


def cmd_train_baseline(args: argparse.Namespace) -> int:
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    train_pool = build_clear_pool(args.seed_base, args.count - args.val_count)
    val_pool = build_clear_pool(args.seed_base + 900_000, args.val_count)

    started = time.monotonic()
    print(f"[baseline] building train dataset from {len(train_pool)} clear scenarios ...")
    train_dataset = build_dataset(train_pool, max_samples_per_scenario=args.samples_per_scenario)
    print(
        f"[baseline] train {len(train_dataset)} samples "
        f"({train_dataset.positive_count} positive) in {time.monotonic()-started:.1f}s"
    )
    val_dataset = build_dataset(val_pool, max_samples_per_scenario=args.samples_per_scenario)
    print(
        f"[baseline] val   {len(val_dataset)} samples ({val_dataset.positive_count} positive)"
    )
    if train_dataset.positive_count == 0 or val_dataset.positive_count == 0:
        print("[baseline] FAIL: no positive hazard labels; pool construction is broken")
        return 2

    limits = TrainingLimits(
        max_epochs=args.epochs,
        max_wall_time_s=args.wall_time_s,
        max_samples=100_000,
        early_stop_patience=3,
    )
    request = TrainingRequest(
        dataset=train_dataset,
        validation_dataset=val_dataset,
        baseline_checkpoint_path=None,
        limits=limits,
        seed=args.seed,
    )
    result = TorchBehaviorCloningTrainer().train(request, out_dir)

    checkpoint_path = Path(result.checkpoint_artifact.uri)
    final_path = out_dir / "baseline.pt"
    checkpoint_path.replace(final_path)

    summary = {
        "checkpoint": str(final_path),
        "input_spec": INPUT_SPEC,
        "metrics_history": result.metrics_history,
        "best_val_loss": result.best_val_loss,
        "best_epoch": result.best_epoch,
        "stopped_early": result.stopped_early,
        "wall_time_s": round(result.wall_time_s, 2),
        "train_dataset": _dataset_summary(train_dataset),
        "val_dataset": _dataset_summary(val_dataset),
    }
    (out_dir / "training-summary.json").write_text(json.dumps(summary, indent=2))
    print(f"[baseline] trained: best_epoch={result.best_epoch} best_val_loss={result.best_val_loss:.4f}")
    print(f"[baseline] checkpoint: {final_path}")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    policy = TorchOcclusionPerceptionAdapter(Path(args.checkpoint))
    descriptor = policy.descriptor
    print(f"[evaluate] checkpoint sha256={descriptor.checkpoint_sha256}")

    reports = []
    ordinary = build_clear_pool(7_500_000, args.ordinary_count)
    occluded = build_occluded_pool(8_800_000, args.occluded_count)

    report = evaluate_suite("ordinary_visible_crossing", ordinary, policy)
    reports.append(report)
    print(report_summary_line(report))

    report_occ = evaluate_suite("occluded_emergence", occluded, policy)
    reports.append(report_occ)
    print(report_summary_line(report_occ))

    matrix = {
        "checkpoint_uri": descriptor.checkpoint_uri,
        "checkpoint_sha256": descriptor.checkpoint_sha256,
        "suites": [r.to_dict() for r in reports],
    }
    out_path = Path(args.output)
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "evaluation-matrix.json").write_text(json.dumps(matrix, indent=2))
    print(f"[evaluate] matrix written to {out_path / 'evaluation-matrix.json'}")
    return 0


def _write_receipt(workspace: Path, terminal_state: str) -> dict:
    """Emit the golden-demo receipt: PASS/FAIL plus the evidence pointers."""

    root = Path(workspace)
    decision_file = root / "promotion-decision.json"
    receipt: dict = {
        "schema": "servo.realityci.campaign-receipt/v1",
        "workspace": str(root),
        "terminal_state": terminal_state,
        "status": "PASS" if terminal_state == "completed_promoted" else "FAIL",
    }
    for name, filename in (
        ("candidate", "candidate.json"),
        ("hidden_exam", "hidden-exam.json"),
        ("regression_report", "regression-report.json"),
        ("promotion_decision", "promotion-decision.json"),
        ("reality_debt", "reality-debt.json"),
    ):
        path = root / filename
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            receipt[f"{name}_sha256"] = payload.get("content_hash")
            receipt[f"{name}_id"] = payload.get("record_id")
    if decision_file.exists():
        decision = json.loads(decision_file.read_text(encoding="utf-8"))
        receipt["decision"] = decision.get("decision")
        receipt["failed_checks"] = [
            c.get("name") for c in decision.get("checks", []) if not c.get("passed")
        ]
    exam_file = root / "hidden-exam.json"
    if exam_file.exists():
        exam = json.loads(exam_file.read_text(encoding="utf-8"))
        counts = exam.get("baseline", {}).get("counts", {})
        cand_counts = exam.get("candidate", {}).get("counts", {})
        receipt["baseline_hidden_success"] = counts
        receipt["candidate_hidden_success"] = cand_counts
    (root / "campaign-receipt.json").write_text(json.dumps(receipt, indent=2))
    return receipt


def _resolve_diagnostician_kind(requested: str) -> str:
    """Resolve 'auto' from credentials without ever inventing a model call.

    'auto' selects gemini only when explicit API-key credentials exist;
    Vertex Application Default Credentials are intentionally NOT probed here
    so that a machine with ambient gcloud auth still gets deterministic
    behavior unless it opts in explicitly.
    """

    if requested != "auto":
        return requested
    import os

    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    return "deterministic"


def cmd_run_campaign(args: argparse.Namespace) -> int:
    from tools.realityci.orchestrator import CampaignEngine
    from tools.realityci.state_machine import CampaignState

    engine = CampaignEngine(
        Path(args.output),
        baseline_checkpoint_path=Path(args.checkpoint),
        diagnostician_kind=_resolve_diagnostician_kind(args.diagnostician),
        diagnostician_model=args.gemini_model,
        training_scenarios=args.training_scenarios,
        hidden_exam_size=args.hidden_exam_size,
        protected_suite_size=args.protected_suite_size,
        training_epochs=args.epochs,
        samples_per_scenario=args.samples_per_scenario,
        promotion_target_success_rate=args.promotion_target,
        promotion_min_lower_bound=args.promotion_floor,
        promotion_max_regression_pp=args.promotion_max_regression_pp,
    )
    terminal = engine.run_to_completion()
    receipt = _write_receipt(Path(args.output), terminal.value)
    print(f"[campaign] terminal state: {terminal.value}")
    print(f"[campaign] receipt status: {receipt['status']}")
    print(f"[campaign] workspace: {Path(args.output)}")
    return 0 if receipt["status"] == "PASS" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="realityci")
    sub = parser.add_subparsers(dest="command", required=True)

    p_train = sub.add_parser("train-baseline", help="train the baseline perception policy on clear crossings")
    p_train.add_argument("--output", type=str, required=True)
    p_train.add_argument("--count", type=int, default=48)
    p_train.add_argument("--val-count", type=int, default=10)
    p_train.add_argument("--seed-base", type=int, default=1_000_000)
    p_train.add_argument("--samples-per-scenario", type=int, default=14)
    p_train.add_argument("--epochs", type=int, default=10)
    p_train.add_argument("--wall-time-s", type=float, default=600.0)
    p_train.add_argument("--seed", type=int, default=0)
    p_train.set_defaults(func=cmd_train_baseline)

    p_eval = sub.add_parser("evaluate", help="evaluate a checkpoint on ordinary and occluded suites")
    p_eval.add_argument("--checkpoint", type=str, required=True)
    p_eval.add_argument("--output", type=str, required=True)
    p_eval.add_argument("--ordinary-count", type=int, default=16)
    p_eval.add_argument("--occluded-count", type=int, default=16)
    p_eval.set_defaults(func=cmd_evaluate)

    p_camp = sub.add_parser("run-campaign", help="run the full fail-to-promote campaign autonomously")
    p_camp.add_argument("--output", type=str, required=True)
    p_camp.add_argument("--checkpoint", type=str, required=True, help="baseline checkpoint path")
    p_camp.add_argument("--diagnostician", type=str, default="deterministic", choices=["deterministic", "gemini"])
    p_camp.add_argument(
        "--gemini-model",
        type=str,
        default=None,
        help="model id override; defaults to the desktop-parity diagnostician model (gemini-3.7-flash)",
    )
    p_camp.add_argument("--training-scenarios", type=int, default=24)
    p_camp.add_argument("--hidden-exam-size", type=int, default=8)
    p_camp.add_argument("--protected-suite-size", type=int, default=4)
    p_camp.add_argument("--epochs", type=int, default=10)
    p_camp.add_argument("--samples-per-scenario", type=int, default=12)
    p_camp.add_argument("--promotion-target", type=float, default=0.85)
    p_camp.add_argument("--promotion-floor", type=float, default=0.45)
    p_camp.add_argument("--promotion-max-regression-pp", type=float, default=5.0)
    p_camp.set_defaults(func=cmd_run_campaign)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
