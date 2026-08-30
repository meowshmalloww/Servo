"""Build Servo's portable CARLA/Project Chrono sedan visualization asset.

The CARLA 0.9.16 distribution ships the Project Chrono sedan as separate
Wavefront body, rim, and tire meshes.  Servo needs one self-contained glTF
scene with four wheels and its native X-forward/Z-up frame converted to
Servo's X-right/Y-up/Z-forward vehicle frame.
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

import numpy as np
import trimesh


def add_scene_geometry(output: trimesh.Scene, source: trimesh.Scene, prefix: str,
                       transform: np.ndarray) -> None:
    for index, geometry in enumerate(source.geometry.values()):
        output.add_geometry(copy.deepcopy(geometry),
                            geom_name=f"{prefix}-{index}",
                            node_name=f"{prefix}-{index}",
                            transform=transform)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()

    source = arguments.source.resolve()
    body = trimesh.load(source / "sedan_chassis_vis.obj", force="scene", process=False)
    rim = trimesh.load(source / "sedan_rim.obj", force="scene", process=False)
    tire = trimesh.load(source / "sedan_tire.obj", force="scene", process=False)

    assembled = trimesh.Scene()
    add_scene_geometry(assembled, body, "body", np.eye(4))

    wheel_x = (1.388, -1.388)
    wheel_y = (0.7979, -0.7979)
    wheel_z = 0.3387
    for axle, x in enumerate(wheel_x):
        for side, y in enumerate(wheel_y):
            transform = trimesh.transformations.translation_matrix((x, y, wheel_z))
            if y < 0.0:
                transform = transform @ trimesh.transformations.rotation_matrix(
                    np.pi, (1.0, 0.0, 0.0))
            prefix = f"wheel-{axle}-{side}"
            add_scene_geometry(assembled, rim, prefix + "-rim", transform)
            add_scene_geometry(assembled, tire, prefix + "-tire", transform)

    # Chrono: +X forward, +Y left, +Z up.
    # Servo's visual frame uses +X lateral, +Y up, +Z forward. Keeping Chrono
    # +Y as visual +X produces a proper rotation (determinant +1) and therefore
    # preserves triangle winding and outward-facing normals.
    chrono_to_servo = np.array(
        [[0.0, 1.0, 0.0, 0.0],
         [0.0, 0.0, 1.0, 0.0],
         [1.0, 0.0, 0.0, 0.0],
         [0.0, 0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    assembled.apply_transform(chrono_to_servo)
    ground_shift = trimesh.transformations.translation_matrix(
        (0.0, -float(assembled.bounds[0, 1]), 0.0))
    assembled.apply_transform(ground_shift)

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_bytes(assembled.export(file_type="glb"))
    print(f"Wrote {arguments.output} ({arguments.output.stat().st_size} bytes)")
    print(f"Bounds: {assembled.bounds.tolist()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
