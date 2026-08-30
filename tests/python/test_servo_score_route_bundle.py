import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "reconstruction" / "servo_score_route_bundle.py"
SPEC = importlib.util.spec_from_file_location("servo_score_route_bundle_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def audit(depth50=0.1, depth95=0.5):
    return {
        "appearance": {
            "registeredPsnrMean": 25.0,
            "registeredPsnrP10": 24.0,
            "registeredSsimMean": 0.76,
            "registeredSsimP10": 0.70,
        },
        "support": {"overallMinimum": 0.95, "lowerHalfMinimum": 0.96},
        "depthAmbiguity": {"relativeStdP50": depth50, "relativeStdP95": depth95},
        "navigationStress": {
            "lateralOffsets": {"supportMinimum": 0.85},
            "yawPitchPerturbations": {"supportMinimum": 0.84},
            "combinedTranslationRotation": {"supportMinimum": 0.83},
        },
    }


class RouteBundleScoreTests(unittest.TestCase):
    def test_visual_can_pass_while_geometry_fails(self):
        route = {"fullRouteCovered": True, "tiles": [{"tileId": "a"}, {"tileId": "b"}]}
        result = MODULE.score(route, {"a": audit(), "b": audit(0.7, 1.5)})
        self.assertTrue(result["visualRoutePassed"])
        self.assertFalse(result["structuralGeometryPassed"])
        self.assertEqual(result["passedChecks"], 10)

    def test_mandatory_motion_failure_rejects_even_at_75_percent(self):
        document = audit()
        document["navigationStress"]["combinedTranslationRotation"]["supportMinimum"] = 0.2
        route = {"fullRouteCovered": True, "tiles": [{"tileId": "a"}]}
        result = MODULE.score(route, {"a": document})
        self.assertFalse(result["visualRoutePassed"])


if __name__ == "__main__":
    unittest.main()
