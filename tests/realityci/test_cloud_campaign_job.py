from __future__ import annotations

from types import SimpleNamespace

from cloud.campaign_job.main import _campaign_engine_overrides, _workspace_prefix


def test_workspace_prefix_is_campaign_scoped(monkeypatch) -> None:
    monkeypatch.setenv("SERVO_GCS_PREFIX", "/realityci/campaigns/")
    assert _workspace_prefix("cam-0123456789abcdef") == "realityci/campaigns/cam-0123456789abcdef"


def test_campaign_job_preserves_campaign_configuration() -> None:
    config = SimpleNamespace(
        diagnostician="gemini",
        diagnostician_model="gemini-3.7-flash",
        seeds_per_arm=3,
        training_seed_pool_size=24,
        hidden_exam_size=8,
        protected_suite_size=4,
        training_epochs=10,
        samples_per_scenario=12,
        promotion_target_success_rate=0.9,
        promotion_min_lower_bound=0.5,
        promotion_max_regression_pp=3.0,
    )
    campaign = SimpleNamespace(
        objective=SimpleNamespace(capability_taxonomy_id="occluded-pedestrian-crossing/v1"),
        config=config,
    )
    values = _campaign_engine_overrides(campaign)
    assert values["diagnostician_kind"] == "gemini"
    assert values["diagnostician_model"] == "gemini-3.7-flash"
    assert values["training_scenarios"] == 24
    assert values["hidden_exam_size"] == 8
