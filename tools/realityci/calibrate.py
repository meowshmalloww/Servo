"""Scenario-band calibration sweep.

Measures baseline-policy failure rate and oracle-perception success rate
across an (ego speed x emergence) grid so the demo band is chosen from
physics + measured perception, not guesswork.  A usable band cell has:
  oracle success == 100%   (a competent detector can pass)
  baseline success <= 50%  (the current policy measurably fails)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.realityci.evaluate import evaluate_scenario
from tools.realityci.policy.torch_perception import TorchOcclusionPerceptionAdapter
from tools.realityci.scenario.runner import OracleConfig, ScenarioRunner
from tools.realityci.schemas.scenario import ScenarioManifest


def _cell_manifest(seed: int, ego_speed: float, emergence_s: float) -> ScenarioManifest:
    import datetime

    from tools.realityci.pools import (
        OBSERVED_PROVENANCE,
        ROUTE,
        WORLD,
        _make_manifest,
    )

    rng_seed = seed
    return _make_manifest(
        rng_seed,
        "cal",
        ego_speed,
        False,
        __import__("tools.realityci.pools", fromlist=["AnyRng"]).AnyRng(rng_seed),
        pedestrian=__import__("tools.realityci.schemas", fromlist=["PedestrianSpec"]).PedestrianSpec(
            crossing_speed_mps=1.6,
            emergence_s=emergence_s,
            crossing_angle_deg=88.0,
            start_lateral_m=2.4,
            end_lateral_m=-3.0,
        ),
        occluder=__import__("tools.realityci.schemas", fromlist=["OccluderSpec"]).OccluderSpec(
            position_s_m=78.0,
            lateral_offset_m=2.1,
        ),
    )


def main() -> int:
    checkpoint = Path(sys.argv[1])
    policy = TorchOcclusionPerceptionAdapter(checkpoint)

    speeds = [10.0, 11.0, 12.0]
    emergences = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5]
    seeds_per_cell = 4

    v_label = "v \\ e"
    header = f"{v_label:>6}" + "".join(f"{e:>10}" for e in emergences)
    print(header)
    for v in speeds:
        row = f"{v:>6}"
        for e in emergences:
            base_pass = 0
            oracle_pass = 0
            for k in range(seeds_per_cell):
                manifest = _cell_manifest(900_000_000 + k, v, e)
                outcome = evaluate_scenario(manifest, policy)
                base_pass += int(outcome.success)
                o = ScenarioRunner(manifest, policy, oracle=OracleConfig(perception=True)).run()
                oracle_pass += int(o.result.value == "success")
            row += f"{base_pass:>4}/{oracle_pass:<2}  {seeds_per_cell}"
        print(row)
    print("\ncell format: baseline_pass/oracle_pass out of", seeds_per_cell)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
