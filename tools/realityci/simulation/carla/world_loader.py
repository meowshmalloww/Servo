"""Load a sealed Servo OpenDRIVE companion into CARLA."""

from __future__ import annotations

from pathlib import Path

from ...hashing import sha256_file
from ...schemas.simulation import ExecutableWorldDescriptor


def load_executable_world(
    client, carla, descriptor: ExecutableWorldDescriptor, *, enable_mesh_visibility: bool = True
):
    xodr_path = Path(descriptor.structure.opendrive_uri)
    if not xodr_path.is_file():
        raise RuntimeError(f"OpenDRIVE artifact is missing: {xodr_path}")
    actual_hash = sha256_file(str(xodr_path))
    if actual_hash != descriptor.structure.opendrive_sha256:
        raise RuntimeError(
            f"OpenDRIVE hash mismatch: expected {descriptor.structure.opendrive_sha256}, computed {actual_hash}"
        )
    text = xodr_path.read_text(encoding="utf-8")
    parameters = carla.OpendriveGenerationParameters(
        vertex_distance=2.0,
        max_road_length=50.0,
        wall_height=0.5,
        additional_width=0.6,
        smooth_junctions=False,
        enable_mesh_visibility=enable_mesh_visibility,
    )
    world = client.generate_opendrive_world(text, parameters)
    if world is None or world.get_map() is None:
        raise RuntimeError("CARLA rejected the generated OpenDRIVE world")
    return world


def configure_synchronous_world(world, fixed_delta_seconds: float, *, no_rendering_mode: bool):
    original = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = fixed_delta_seconds
    settings.no_rendering_mode = no_rendering_mode
    settings.substepping = True
    settings.max_substep_delta_time = min(0.01, fixed_delta_seconds)
    settings.max_substeps = max(1, int(round(fixed_delta_seconds / settings.max_substep_delta_time)))
    world.apply_settings(settings)
    return original
