"""Asynchronous Google Cloud Run Job for one complete RealityCI campaign.

The job restores a sealed campaign workspace from Cloud Storage, executes the
real Google ADK graph, and mirrors the resulting ordered events, checkpoints,
exam, decision and receipt back to the same prefix.  CARLA and Gaussian
reconstruction are intentionally not run here: those remain registered local
workers because their verified runtimes are Windows/GPU-bound.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.realityci.adk_graph import ADK_VERSION_INSTALLED, run_campaign_on_adk
from tools.realityci.hashing import canonical_json_bytes, sha256_digest
from tools.realityci.schemas.campaign import Campaign


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _workspace_prefix(campaign_id: str) -> str:
    prefix = os.environ.get("SERVO_GCS_PREFIX", "campaigns").strip("/")
    return f"{prefix}/{campaign_id}"


def _storage_bucket():
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RuntimeError("google-cloud-storage is required in the campaign job") from exc
    return storage.Client().bucket(_required_env("SERVO_GCS_BUCKET"))


def _write_firestore_index(campaign_id: str, payload: dict[str, Any]) -> None:
    database = os.environ.get("SERVO_FIRESTORE_DATABASE", "").strip()
    if not database:
        return
    try:
        from google.cloud import firestore
    except ImportError as exc:
        raise RuntimeError("google-cloud-firestore is required in the campaign job") from exc
    collection = os.environ.get("SERVO_FIRESTORE_COLLECTION", "servo_campaigns").strip()
    if not collection or "/" in collection:
        raise RuntimeError("SERVO_FIRESTORE_COLLECTION must be one collection name")
    prefix = _workspace_prefix(campaign_id)
    index = {
        "schema": "servo.firestore-campaign-index/v1",
        "campaign_id": campaign_id,
        "state": payload["state"],
        "terminal": payload["state"] in {"completed", "failed"},
        "updated_at": payload["updated_at"],
        "commit_sha": payload["commit_sha"],
        "cloud_run_execution": payload["cloud_run_execution"],
        "artifact_prefix": f"gs://{_required_env('SERVO_GCS_BUCKET')}/{prefix}",
        "storage_contract": "metadata-only; artifacts-in-gcs",
    }
    firestore.Client(
        project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None,
        database=database,
    ).collection(collection).document(campaign_id).set(index, merge=True)


def _download_workspace(campaign_id: str, root: Path) -> None:
    bucket = _storage_bucket()
    base = _workspace_prefix(campaign_id)
    found = False
    for blob in bucket.list_blobs(prefix=f"{base}/"):
        relative = blob.name[len(base) :].lstrip("/")
        if not relative or relative.endswith("/"):
            continue
        found = True
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(target))
    if not found:
        raise RuntimeError(f"campaign workspace not found at gs://{bucket.name}/{base}")


def _upload_file(campaign_id: str, root: Path, path: Path) -> None:
    bucket = _storage_bucket()
    name = f"{_workspace_prefix(campaign_id)}/{path.relative_to(root).as_posix()}"
    bucket.blob(name).upload_from_filename(str(path))


def _upload_workspace(campaign_id: str, root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            _upload_file(campaign_id, root, path)


def _campaign_engine_overrides(campaign: Campaign) -> dict[str, Any]:
    config = campaign.config
    return {
        "objective_capability": campaign.objective.capability_taxonomy_id,
        "diagnostician_kind": config.diagnostician,
        "diagnostician_model": config.diagnostician_model,
        "seeds_per_arm": config.seeds_per_arm,
        "training_scenarios": config.training_seed_pool_size,
        "hidden_exam_size": config.hidden_exam_size,
        "protected_suite_size": config.protected_suite_size,
        "training_epochs": config.training_epochs,
        "samples_per_scenario": config.samples_per_scenario,
        "promotion_target_success_rate": config.promotion_target_success_rate,
        "promotion_min_lower_bound": config.promotion_min_lower_bound,
        "promotion_max_regression_pp": config.promotion_max_regression_pp,
    }


def _write_state(root: Path, campaign_id: str, state: str, **detail: Any) -> None:
    payload: dict[str, Any] = {
        "schema": "servo.cloud-campaign-execution/v1",
        "campaign_id": campaign_id,
        "state": state,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cloud_run_execution": os.environ.get("CLOUD_RUN_EXECUTION", ""),
        "cloud_run_task_index": os.environ.get("CLOUD_RUN_TASK_INDEX", "0"),
        "commit_sha": os.environ.get("SERVO_COMMIT_SHA", "unknown"),
    }
    payload.update(detail)
    unsigned = canonical_json_bytes(payload)
    payload["content_hash"] = sha256_digest(unsigned)
    path = root / "cloud-execution-receipt.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _upload_file(campaign_id, root, path)
    _write_firestore_index(campaign_id, payload)


def main() -> int:
    campaign_id = _required_env("SERVO_CAMPAIGN_ID")
    root = Path(os.environ.get("SERVO_CAMPAIGN_ROOT", "/workspace/campaigns")) / campaign_id
    root.mkdir(parents=True, exist_ok=True)
    try:
        _download_workspace(campaign_id, root)
        campaign_path = root / "campaign.json"
        campaign = Campaign.model_validate_json(campaign_path.read_text(encoding="utf-8"))
        baseline = root / "baseline-checkpoint.pt"
        if not baseline.is_file():
            raise RuntimeError(
                "campaign is missing staged baseline-checkpoint.pt; dispatch is rejected"
            )
        _write_state(
            root,
            campaign_id,
            "running",
            orchestrator=ADK_VERSION_INSTALLED,
            model=campaign.config.diagnostician_model,
        )
        result = run_campaign_on_adk(
            root,
            baseline,
            **_campaign_engine_overrides(campaign),
        )
        _upload_workspace(campaign_id, root)
        _write_state(
            root,
            campaign_id,
            "completed",
            orchestrator=ADK_VERSION_INSTALLED,
            terminal_state=result.terminal_state.value,
            adk_event_count=result.adk_event_count,
            adk_session_id=result.session_id,
            adk_steps=result.steps,
        )
        print(json.dumps({"campaign_id": campaign_id, "state": "completed"}))
        return 0
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        try:
            _write_state(root, campaign_id, "failed", error=error)
            _upload_workspace(campaign_id, root)
        except Exception:
            pass
        print(json.dumps({"campaign_id": campaign_id, "state": "failed", "error": error}))
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
