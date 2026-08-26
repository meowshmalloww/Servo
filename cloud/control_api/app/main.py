"""Servo RealityCI control API.

Wraps the durable CampaignEngine with an HTTP surface suitable for Cloud
Run.  The same engine runs locally against a workspace directory; the API
adds authentication and job-shaped entrypoints.  Deployment requires GCP
credentials; see cloud/infra/README.md.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from tools.realityci.hashing import new_record_id
from tools.realityci.orchestrator import CampaignEngine, load_events
from tools.realityci.schemas.campaign import Campaign
from tools.realityci.schemas.core import DomainEvent
from tools.realityci.state_machine import TERMINAL_STATES, CampaignState

from .object_store import gcs_enabled, sync_from_gcs, sync_to_gcs

WORKSPACE_ROOT = Path(os.environ.get("SERVO_CAMPAIGN_ROOT", "./campaigns"))
API_TOKEN = os.environ.get("SERVO_API_TOKEN", "")


def require_token(authorization: str = Header(default="")) -> None:
    if not API_TOKEN:
        return
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


app = FastAPI(title="servo-realityci-api", version="0.1.0")


class CreateCampaignRequest(BaseModel):
    baseline_checkpoint_uri: str = Field(min_length=1)
    objective_capability: str = "occluded-pedestrian-crossing/v1"
    training_scenarios: int = Field(ge=4, default=24)
    hidden_exam_size: int = Field(ge=2, default=8)
    protected_suite_size: int = Field(ge=2, default=4)
    training_epochs: int = Field(ge=1, default=10)
    samples_per_scenario: int = Field(ge=4, default=12)
    promotion_target_success_rate: float = Field(ge=0.0, le=1.0, default=0.9)
    promotion_min_lower_bound: float = Field(ge=0.0, le=1.0, default=0.5)
    promotion_max_regression_pp: float = Field(gt=0.0, default=3.0)


def _engine_for(campaign_id: str) -> CampaignEngine:
    root = WORKSPACE_ROOT / campaign_id
    if gcs_enabled():
        sync_from_gcs(campaign_id, root)
    if not root.exists():
        raise HTTPException(status_code=404, detail="campaign not found")

    # Reconstruct the engine from the sealed campaign record so that resumed
    # steps use exactly the gates and sizes the campaign was created with.
    campaign = Campaign.model_validate_json(
        (root / "campaign.json").read_text(encoding="utf-8")
    )
    return CampaignEngine(
        root,
        baseline_checkpoint_path=Path(campaign.baseline_policy.checkpoint_uri),
        objective_capability=campaign.objective.capability_taxonomy_id,
        diagnostician_kind=campaign.config.diagnostician,
        seeds_per_arm=campaign.config.seeds_per_arm,
        training_scenarios=campaign.config.training_seed_pool_size,
        hidden_exam_size=campaign.config.hidden_exam_size,
        protected_suite_size=campaign.config.protected_suite_size,
        training_epochs=campaign.config.training_epochs,
        samples_per_scenario=campaign.config.samples_per_scenario,
        promotion_target_success_rate=campaign.config.promotion_target_success_rate,
        promotion_min_lower_bound=campaign.config.promotion_min_lower_bound,
        promotion_max_regression_pp=campaign.config.promotion_max_regression_pp,
    )


def _persist(campaign_id: str) -> None:
    if gcs_enabled():
        sync_to_gcs(campaign_id, WORKSPACE_ROOT / campaign_id)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/v1/campaigns", dependencies=[Depends(require_token)])
def create_campaign(request: CreateCampaignRequest) -> dict:
    campaign_id = new_record_id("cam")
    engine = CampaignEngine(
        WORKSPACE_ROOT / campaign_id,
        baseline_checkpoint_path=Path(request.baseline_checkpoint_uri),
        objective_capability=request.objective_capability,
        training_scenarios=request.training_scenarios,
        hidden_exam_size=request.hidden_exam_size,
        protected_suite_size=request.protected_suite_size,
        training_epochs=request.training_epochs,
        samples_per_scenario=request.samples_per_scenario,
        promotion_target_success_rate=request.promotion_target_success_rate,
        promotion_min_lower_bound=request.promotion_min_lower_bound,
        promotion_max_regression_pp=request.promotion_max_regression_pp,
        campaign_id=campaign_id,
    )
    _persist(campaign_id)
    return {"campaign_id": engine.campaign_id, "state": engine.current_state().value}


@app.post("/v1/campaigns/{campaign_id}/step", dependencies=[Depends(require_token)])
def step_campaign(campaign_id: str) -> dict:
    engine = _engine_for(campaign_id)
    state = engine.step_once()
    _persist(campaign_id)
    return {
        "campaign_id": campaign_id,
        "state": state.value,
        "terminal": state in TERMINAL_STATES,
    }


@app.post("/v1/campaigns/{campaign_id}/run", dependencies=[Depends(require_token)])
def run_campaign(campaign_id: str) -> dict:
    engine = _engine_for(campaign_id)
    terminal = engine.run_to_completion()
    _persist(campaign_id)
    return {"campaign_id": campaign_id, "state": terminal.value}


@app.get("/v1/campaigns/{campaign_id}/state", dependencies=[Depends(require_token)])
def campaign_state(campaign_id: str) -> dict:
    engine = _engine_for(campaign_id)
    return {
        "campaign_id": campaign_id,
        "state": engine.current_state().value,
        "terminal": engine.current_state() in TERMINAL_STATES,
    }


@app.get("/v1/campaigns/{campaign_id}/events", dependencies=[Depends(require_token)])
def campaign_events(campaign_id: str, after_sequence: int = 0) -> dict:
    engine = _engine_for(campaign_id)
    events: list[DomainEvent] = [
        e for e in load_events(engine.paths.events_file) if e.sequence > after_sequence
    ]
    return {
        "campaign_id": campaign_id,
        "events": [e.model_dump(mode="json") for e in events],
    }
