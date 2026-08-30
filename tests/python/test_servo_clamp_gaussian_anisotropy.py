import importlib.util
import math
import struct
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[2] / "tools" / "reconstruction" / "servo_clamp_gaussian_anisotropy.py"
SPEC = importlib.util.spec_from_file_location("servo_clamp_gaussian_anisotropy", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ClampGaussianAnisotropyTests(unittest.TestCase):
    def test_caps_only_long_axes_and_preserves_vertices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.ply"
            output = root / "output.ply"
            header = (
                "ply\nformat binary_little_endian 1.0\nelement vertex 2\n"
                "property float x\nproperty float scale_0\nproperty float scale_1\n"
                "property float scale_2\nend_header\n"
            ).encode("ascii")
            source.write_bytes(
                header
                + struct.pack("<8f", 1.0, 0.0, 1.0, 8.0, 2.0, -2.0, -1.5, -1.0)
            )
            receipt = MODULE.clamp(source, output, 10.0)
            self.assertEqual(receipt["gaussianCount"], 2)
            self.assertEqual(receipt["modifiedGaussians"], 1)
            payload = output.read_bytes()[len(header):]
            values = struct.unpack("<8f", payload)
            self.assertAlmostEqual(values[3], math.log(10.0), places=5)
            self.assertEqual(values[4:], (2.0, -2.0, -1.5, -1.0))


if __name__ == "__main__":
    unittest.main()
