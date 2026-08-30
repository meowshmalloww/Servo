"""Real packaged-CARLA checks; skipped when the external runtime is absent."""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

from tools.realityci.simulation.carla.client import connect_verified, full_runtime_preflight, validate_opendrive_dry_run
from tools.realityci.simulation.carla.discovery import discover_runtime, find_free_port
from tools.realityci.simulation.carla.process_manager import CarlaProcessManager
from tools.realityci.simulation.worlds.opendrive_generator import generate_single_corridor_opendrive


@pytest.fixture()
def running_carla(tmp_path_factory):
    discovery = discover_runtime(os.environ.get("SERVO_CARLA_ROOT"), import_api=True)
    if not discovery.ready or not discovery.root:
        pytest.skip("packaged CARLA 0.9.16 runtime is not registered")
    runtime_dir = tmp_path_factory.mktemp("carla-integration-runtime")
    manager = CarlaProcessManager(Path(discovery.root), runtime_dir / "server.json")
    rpc_port, traffic_port = find_free_port(), find_free_port()
    while traffic_port == rpc_port:
        traffic_port = find_free_port()
    manager.launch(discovery, require_rendering=True, rpc_port=rpc_port, traffic_manager_port=traffic_port)
    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        try:
            connect_verified(discovery.python_api_path or "", "127.0.0.1", rpc_port, 2.0)
            break
        except Exception:
            time.sleep(0.5)
    else:
        manager.stop()
        pytest.fail("owned CARLA server did not become ready")
    try:
        yield discovery, rpc_port
    finally:
        manager.stop()
        assert not manager.verify_record()


def test_runtime_physics_sensor_and_cleanup_smoke(running_carla) -> None:
    discovery, rpc_port = running_carla
    result = full_runtime_preflight(discovery.python_api_path or "", "127.0.0.1", rpc_port, rendering=True)
    assert result["client_version"] == result["server_version"] == "0.9.16"
    assert result["vehicle_blueprint"] == "vehicle.lincoln.mkz_2020"
    assert result["autopilot"] is False
    assert result["distance_moved_m"] > 0.1
    assert result["sensor_frame_bytes"] > 0


def test_generated_opendrive_explicit_control_physics(running_carla, tmp_path: Path) -> None:
    discovery, rpc_port = running_carla
    xodr = tmp_path / "corridor.xodr"
    generate_single_corridor_opendrive(
        np.array([[0.0, 0.0, 0.0], [25.0, 0.0, 0.0], [50.0, 1.0, 0.0]]),
        xodr,
        lane_width_m=3.5,
        shoulder_width_m=0.5,
        driving_side="right",
        include_opposing_lane=False,
    )
    result = validate_opendrive_dry_run(discovery.python_api_path or "", "127.0.0.1", rpc_port, xodr)
    assert result["ready"] is True
    assert result["autopilot"] is False
    assert result["distance_moved_m"] > 0.5
