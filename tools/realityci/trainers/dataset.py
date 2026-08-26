"""Behavior-cloning dataset construction from deterministic scenario state.

Labels are computed from scenario ground truth, never from a policy: a
sample is positive exactly when an unbraking ego would conflict with the
currently visible pedestrian within the prediction horizon.  This makes
P(hazard) a sound braking signal under thresholding.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..scenario.dynamics import pedestrian_world_position
from ..scenario.runner import RunnerTiming, ScenarioRunner
from ..schemas.scenario import ScenarioManifest


PREDICTION_HORIZON_S = 2.5
TRAINING_HORIZON_S = 2.5


@dataclass(frozen=True)
class LabeledSample:
    frame_rgb: np.ndarray
    previous_frame_rgb: np.ndarray
    ego_speed_mps: float
    label: int
    time_s: float
    scenario_seed: int


@dataclass(frozen=True)
class LabeledDataset:
    samples: tuple[LabeledSample, ...]

    def __len__(self) -> int:
        return len(self.samples)

    @property
    def positive_count(self) -> int:
        return sum(1 for sample in self.samples if sample.label == 1)


class _NoBrakeProbePolicy:
    def reset(self, seed: int) -> None:
        del seed

    def observe(self, packet) -> float:
        del packet
        return 0.0


def hazard_label(
    manifest: ScenarioManifest,
    elapsed_s: float,
    ego_front_s: float,
    ego_speed_mps: float,
    cross_s: float,
    visible: bool,
    timing: RunnerTiming = RunnerTiming(),
    prediction_horizon_s: float = PREDICTION_HORIZON_S,
) -> bool:
    """True iff the currently visible pedestrian will occupy the ego corridor
    by the time the unbraking ego reaches them, accounting for the fact that
    the pedestrian only starts walking at `emergence_s`.
    """

    ped_spec = manifest.pedestrian
    if ped_spec is None or not visible or ego_speed_mps <= 0.05:
        return False
    ped_s, ped_y = pedestrian_world_position(cross_s, ped_spec, elapsed_s)
    if ped_s <= ego_front_s:
        return False
    t_reach = (ped_s - ego_front_s) / ego_speed_mps
    if t_reach > prediction_horizon_s:
        return False
    walk_start_delay = max(0.0, ped_spec.emergence_s - elapsed_s)
    t_walking = t_reach - walk_start_delay
    if t_walking <= 0.0:
        return False
    angle_rad = math.radians(ped_spec.crossing_angle_deg)
    direction = 1.0 if ped_spec.end_lateral_m >= ped_spec.start_lateral_m else -1.0
    y_future = ped_y + ped_spec.crossing_speed_mps * math.sin(angle_rad) * direction * t_walking
    corridor_half = manifest.ego.lane_width_m / 2.0 + ped_spec.width_m / 2.0
    return abs(y_future) < corridor_half


def build_dataset(manifests: list[ScenarioManifest], max_samples_per_scenario: int) -> LabeledDataset:
    if max_samples_per_scenario <= 0:
        raise ValueError("max_samples_per_scenario must be positive")
    timing = RunnerTiming()
    samples: list[LabeledSample] = []
    for manifest in manifests:
        runner = ScenarioRunner(manifest, _NoBrakeProbePolicy(), capture_frames=True, timing=timing)
        outcome = runner.run()
        cross_s = runner._pedestrian_cross_s()

        frame_rows: list[tuple[object, np.ndarray]] = []
        for row in outcome.telemetry:
            frame = outcome.frames.get(row.time_s)
            if frame is not None:
                frame_rows.append((row, frame))
        if not frame_rows:
            continue

        stride = max(1, math.ceil(len(frame_rows) / max_samples_per_scenario))
        paired: list[tuple[object, np.ndarray, np.ndarray]] = []
        for index, (row, frame) in enumerate(frame_rows):
            previous_frame = frame_rows[index - 1][1] if index > 0 else frame
            paired.append((row, frame, previous_frame))

        labeled: list[tuple[object, np.ndarray, np.ndarray, int]] = []
        for row, frame, previous_frame in paired:
            visible = row.gt_visible_fraction >= timing.visibility_threshold
            front = row.ego_s_m + manifest.ego.length_m / 2.0
            label = hazard_label(
                manifest=manifest,
                elapsed_s=row.time_s,
                ego_front_s=front,
                ego_speed_mps=row.ego_speed_mps,
                cross_s=cross_s,
                visible=visible,
                timing=timing,
                prediction_horizon_s=TRAINING_HORIZON_S,
            )
            labeled.append((row, frame, previous_frame, int(label)))

        positives = [item for item in labeled if item[3] == 1]
        negatives = [item for item in labeled if item[3] == 0]

        kept_positives = positives[:: max(1, math.ceil(len(positives) / max_samples_per_scenario))]
        negative_budget = min(len(negatives), 2 * len(kept_positives) + 4)
        kept_negatives = (
            negatives[:: max(1, math.ceil(len(negatives) / negative_budget))][:negative_budget]
            if negative_budget > 0
            else []
        )

        for row, frame, previous_frame, label in kept_positives + kept_negatives:
            samples.append(
                LabeledSample(
                    frame_rgb=frame,
                    previous_frame_rgb=previous_frame,
                    ego_speed_mps=row.ego_speed_mps,
                    label=label,
                    time_s=row.time_s,
                    scenario_seed=manifest.seed,
                )
            )
    return LabeledDataset(samples=tuple(samples))
