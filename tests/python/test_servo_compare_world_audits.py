import unittest

from tools.reconstruction.servo_compare_world_audits import compare


def audit(psnr: float, ssim: float, heldout_psnr: float, heldout_ssim: float):
    return {"appearance": {
        "registeredPsnrMean": psnr,
        "registeredSsimMean": ssim,
        "heldoutPsnrMean": heldout_psnr,
        "heldoutSsimMean": heldout_ssim,
    }}


class CompareWorldAuditsTests(unittest.TestCase):
    def test_requires_material_gain(self):
        control = audit(23.0, 0.75, 22.0, 0.72)
        self.assertTrue(compare(control, audit(23.6, 0.77, 22.3, 0.73))["passed"])
        self.assertFalse(compare(control, audit(23.1, 0.76, 22.1, 0.725))["passed"])

    def test_brush_like_regression_keeps_control(self):
        result = compare(
            audit(23.4867, 0.77585, 23.4738, 0.77072),
            audit(20.6879, 0.64969, 20.8400, 0.65683),
        )
        self.assertEqual(result["decision"], "keep-control")
        self.assertLess(result["deltas"]["registeredPsnrMean"], -2.7)

    def test_registered_only_external_audits_are_supported(self):
        control = {"appearance": {
            "registeredPsnrMean": 26.5,
            "registeredSsimMean": 0.80,
            "registeredPsnrP10": 25.1,
            "registeredSsimP10": 0.74,
        }}
        candidate = {"appearance": {
            "registeredPsnrMean": 24.0,
            "registeredSsimMean": 0.82,
            "registeredPsnrP10": 16.8,
            "registeredSsimP10": 0.51,
        }}
        result = compare(control, candidate)
        self.assertFalse(result["passed"])
        self.assertFalse(result["heldoutCompared"])
        self.assertLess(result["deltas"]["registeredPsnrP10"], -8.0)


if __name__ == "__main__":
    unittest.main()
