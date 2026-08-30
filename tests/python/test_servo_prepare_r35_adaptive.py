from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "reconstruction" / "servo_prepare_r35_adaptive.py"
SPEC = importlib.util.spec_from_file_location("servo_prepare_r35_adaptive_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class PrepareR35AdaptiveTests(unittest.TestCase):
    def test_build_config_removes_fixed_gaussian_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "base.json"
            base.write_text(
                json.dumps(
                    {
                        "configurationHash": "sha256:parent",
                        "pipelineCodeHash": "sha256:old",
                        "targetGaussians": 1_500_000,
                        "maxGaussians": 3_000_000,
                    }
                ),
                encoding="utf-8",
            )
            config = module.build_config(
                base=base,
                output=Path(directory) / "output",
                steps=12_000,
                seed=42,
            )
            self.assertEqual(config["targetGaussians"], 0)
            self.assertEqual(config["maxGaussians"], 0)
            self.assertEqual(config["gaussianBudgetPolicy"], module.BUDGET_POLICY)
            self.assertEqual(config["refineScale2dStopIter"], 10_000)
            self.assertTrue(config["diagnosticProvenance"]["nonPublishable"])


if __name__ == "__main__":
    unittest.main()
