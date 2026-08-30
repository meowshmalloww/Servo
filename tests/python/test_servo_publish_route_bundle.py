from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "reconstruction" / "servo_publish_route_bundle.py"
SPEC = importlib.util.spec_from_file_location("servo_publish_route_bundle_test", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PublishRouteBundleTests(unittest.TestCase):
    def test_parse_bindings_requires_unique_tile_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            bindings = MODULE.parse_bindings([f"tile-a={path}"])
            self.assertEqual(bindings, {"tile-a": path.resolve()})
            with self.assertRaises(ValueError):
                MODULE.parse_bindings([f"tile-a={path}", f"tile-a={path}"])

    def test_link_or_copy_preserves_exact_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.ply"
            target = root / "target.ply"
            source.write_bytes(b"ply\nroute-tile\n")
            method = MODULE.link_or_copy(source, target)
            self.assertIn(method, {"hardlink", "copy"})
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(MODULE.sha256(target), MODULE.sha256(source))

    def test_atomic_json_has_stable_sorted_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            MODULE.atomic_json(output, {"z": 1, "a": 2})
            self.assertEqual(output.read_text(encoding="utf-8"), '{\n  "a": 2,\n  "z": 1\n}\n')


if __name__ == "__main__":
    unittest.main()
