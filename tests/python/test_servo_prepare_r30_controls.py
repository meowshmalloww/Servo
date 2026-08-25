from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


REPOSITORY = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    REPOSITORY / "tools" / "reconstruction" / "servo_prepare_r30_controls.py"
)
SPEC = importlib.util.spec_from_file_location("servo_prepare_r30_controls", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
prepare = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prepare
SPEC.loader.exec_module(prepare)


class PrepareR30ControlsTests(unittest.TestCase):
    def test_matched_configs_change_only_region_treatment(self) -> None:
        base = REPOSITORY / "tmp" / "r28-current-confidence-v4-control-1500-config.json"
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            prepare, "pipeline_hash", return_value="sha256:" + "1" * 64
        ), mock.patch.object(prepare, "source_commit", return_value="abc123"):
            root = Path(directory)
            control = prepare.build_config(
                base=base,
                treatment="footprint-control",
                steps=300,
                seed=42,
                output=root / "control",
            )
            region = prepare.build_config(
                base=base,
                treatment="region-aware",
                steps=300,
                seed=42,
                output=root / "region",
            )
        self.assertNotIn("regionAwareDensification", control)
        self.assertIn("regionAwareDensification", region)
        self.assertEqual(control["finalFitSteps"], 50)
        self.assertEqual(control["refineScale2dStopIter"], 250)
        self.assertEqual(control["coverageAwareDensification"], region["coverageAwareDensification"])
        for key in (
            "maxSteps",
            "finalFitSteps",
            "coarseSteps",
            "targetGaussians",
            "maxGaussians",
            "refineStartIter",
            "refineEvery",
            "refineScale2dStopIter",
            "denseGeometryStart",
            "depthLayerVarianceStart",
            "observedDetailStart",
            "surfaceAlignmentStart",
            "growGrad2d",
            "seed",
        ):
            self.assertEqual(control[key], region[key])
        self.assertFalse(region["regionAwareDensification"]["lossesChanged"])
        self.assertFalse(region["regionAwareDensification"]["generatedViewsUsed"])

    def test_rejects_unreviewed_budget(self) -> None:
        base = REPOSITORY / "tmp" / "r28-current-confidence-v4-control-1500-config.json"
        with self.assertRaisesRegex(RuntimeError, "300, 750, or 1500"):
            prepare.build_config(
                base=base,
                treatment="region-aware",
                steps=7_000,
                seed=42,
                output=Path("unused"),
            )


if __name__ == "__main__":
    unittest.main()
