import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "reconstruction" / "servo_prepare_route_tiles.py"
SPEC = importlib.util.spec_from_file_location("servo_prepare_route_tiles_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RouteTileTests(unittest.TestCase):
    def test_ranges_cover_route_with_overlap(self):
        self.assertEqual(
            MODULE.tile_ranges(373, 96, 24),
            [(0, 96), (72, 168), (144, 240), (216, 312), (277, 373)],
        )

    def test_prepare_preserves_all_camera_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            sparse = root / "sparse" / "0"
            images = root / "images"
            sparse.mkdir(parents=True)
            images.mkdir()
            (sparse / "cameras.txt").write_text(
                "1 PINHOLE 8 6 10 10 4 3\n", encoding="utf-8"
            )
            image_rows = []
            point_rows = []
            for index in range(6):
                name = f"frame_{index:03d}.png"
                Image.new("RGB", (8, 6), (index, index, index)).save(images / name)
                image_rows.append(f"{index + 1} 1 0 0 0 0 0 0 1 {name}\n0 0 {index + 1}\n")
                point_rows.append(f"{index + 1} {index} 0 1 1 2 3 0 {index + 1} 0\n")
            (sparse / "images.txt").write_text("".join(image_rows), encoding="utf-8")
            (sparse / "points3D.txt").write_text("".join(point_rows), encoding="utf-8")
            output = Path(directory) / "tiles"
            receipt = MODULE.prepare(root, output, tile_size=4, overlap=2)
            self.assertTrue(receipt["fullRouteCovered"])
            self.assertEqual(receipt["tileCount"], 2)
            names = set()
            for tile in receipt["tiles"]:
                names.update(path.name for path in (Path(tile["dataset"]) / "images").iterdir())
            self.assertEqual(names, {f"frame_{index:03d}.png" for index in range(6)})


if __name__ == "__main__":
    unittest.main()
