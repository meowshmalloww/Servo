from __future__ import annotations

import json
import socket
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest
import torch
from fastapi.testclient import TestClient

from tools.realityci.driving.policies.tinydrive import ServoTinyDriveNetwork, create_initial_checkpoint
from tools.realityci.driving.controllers import PurePursuitPidController
from tools.realityci.driving.safety import ActionSafetyGuard
from tools.realityci.driving.training.dataset import seal_dataset_manifest
from tools.realityci.driving.campaign import required_counterfactual_arms, seal_recovery_curriculum
from tools.realityci.schemas.driving import CameraIntrinsics, DirectVehicleControl, ObservationSource, Pose, Quaternion, TrajectoryAction, TrajectoryWaypoint, Vector3
from tools.realityci.schemas.simulation import SimulationSessionState
from tools.realityci.simulation.carla.coordinates import (
    CoordinateTransform,
    default_handedness_matrix,
    invert_matrix,
    quaternion_to_matrix,
    validate_inverse_pair,
)
from tools.realityci.simulation.carla.runner import (
    _configure_vehicle_weather_physics,
    _configure_ground_contact_physics,
    _opencv_camera_pose_from_carla,
    _route_corridor_guard,
    _route_goal_reached,
    _route_stabilized_control,
    _route_target_ego,
)
from tools.realityci.simulation.carla.discovery import discover_runtime, find_free_port, port_available, port_block_available
from tools.realityci.simulation.carla.evaluator import classify_infrastructure_invalid, route_metrics
from tools.realityci.simulation.carla.process_manager import CarlaProcessManager
from tools.realityci.simulation.carla.sensor_barrier import SensorBarrier, SensorSynchronizationError
from tools.realityci.simulation.session_store import SessionStore, SimulationTransitionError, atomic_write_json
from tools.realityci.simulation.worlds.opendrive_generator import generate_single_corridor_opendrive
from tools.realityci.simulation.worlds.opendrive_validator import validate_opendrive
from tools.realityci.simulation.worlds.executable_bundle import (
    carla_centerline_to_opendrive,
    extend_road_reference_endpoints,
    inferred_reference_offset_for_driving_lane,
    offset_reference_line_from_lane_center,
    road_centerline_from_camera_path,
)
from tools.realityci.simulation.rendering.base import ObservationRenderRequest, ObservationRenderResult, ObservationRenderer
from tools.realityci.simulation.rendering.hybrid_compositor import HybridGaussianCarlaObservationRenderer
from tools.realityci.simulation.rendering.servo_gaussian import ServoGaussianObservationRenderer
from cloud.control_api.app.main import app


def _fake_carla(root: Path, version: str = "0.9.16") -> None:
    (root / "CarlaUE4.exe").parent.mkdir(parents=True)
    (root / "CarlaUE4.exe").write_bytes(b"fake-packaged-server")
    dist = root / "PythonAPI" / "carla" / "dist"
    dist.mkdir(parents=True)
    (dist / f"carla-{version}-cp311-win_amd64.whl").write_bytes(b"fake-wheel")
    agent = root / "PythonAPI" / "carla" / "agents" / "navigation" / "behavior_agent.py"
    agent.parent.mkdir(parents=True)
    agent.write_text("# fake agent\n", encoding="utf-8")


def test_runtime_discovery_accepts_only_pinned_packaged_layout(tmp_path: Path) -> None:
    good = tmp_path / "CARLA_0.9.16"
    _fake_carla(good)
    result = discover_runtime(str(good), import_api=False)
    assert result.ready and result.client_version == "0.9.16"
    bad = tmp_path / "CARLA_0.9.15"
    _fake_carla(bad, "0.9.15")
    mismatch = discover_runtime(str(bad), import_api=False)
    assert not mismatch.ready
    assert "version mismatch" in " ".join(mismatch.errors).lower()


def test_runtime_discovery_rejects_source_checkout(tmp_path: Path) -> None:
    (tmp_path / "PythonAPI").mkdir()
    result = discover_runtime(str(tmp_path), import_api=False)
    assert not result.ready
    assert any("CarlaUE4.exe" in error for error in result.errors)


def test_rpc_port_ownership_probe() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        assert not port_available(listener.getsockname()[1])


def test_carla_port_allocator_reserves_rpc_streaming_and_router_block() -> None:
    first = find_free_port()
    assert port_block_available(first, 3)


def test_stale_owned_process_record_is_not_trusted(tmp_path: Path) -> None:
    executable = tmp_path / "CarlaUE4.exe"
    executable.write_bytes(b"x")
    record = tmp_path / "server.json"
    atomic_write_json(record, {"pid": 2_147_483_647, "executable": str(executable), "executable_sha256": "wrong"})
    assert not CarlaProcessManager(tmp_path, record).verify_record()


def test_coordinate_transform_roundtrip_and_inversion() -> None:
    forward = default_handedness_matrix(2.0)
    inverse = invert_matrix(forward)
    assert validate_inverse_pair(forward, inverse) < 1e-10
    transform = CoordinateTransform(forward, inverse)
    point = Vector3(x=3.0, y=1.0, z=-4.0)
    assert transform.position_carla_to_servo(transform.position_servo_to_carla(point)).model_dump() == pytest.approx(point.model_dump())
    with pytest.raises(ValueError, match="not invertible"):
        invert_matrix((0.0,) * 16)


def test_carla_camera_axes_convert_to_opencv_c2w_without_upside_down_motion() -> None:
    forward = default_handedness_matrix(1.0)
    transform = CoordinateTransform(forward, invert_matrix(forward))
    camera = SimpleNamespace(
        location=SimpleNamespace(x=2.0, y=3.0, z=4.0),
        rotation=SimpleNamespace(pitch=0.0, yaw=0.0, roll=0.0),
    )
    pose = _opencv_camera_pose_from_carla(transform, camera)
    # Identity CARLA camera axes are forward/right/up.  In Servo's OpenCV
    # convention they must become right/down/forward, not an actor quaternion.
    assert quaternion_to_matrix(pose.orientation) == pytest.approx(
        np.diag([1.0, -1.0, -1.0]), abs=1e-7
    )
    assert pose.position.model_dump() == pytest.approx({"x": 3.0, "y": 4.0, "z": -2.0})


def test_inferred_road_is_below_camera_path_without_mutating_camera_evidence() -> None:
    camera_path = np.array([[0.0, 0.0, 2.0], [5.0, 1.0, 2.5], [10.0, 2.0, 3.0]])
    original = camera_path.copy()
    road = road_centerline_from_camera_path(camera_path, 1.4)
    assert camera_path == pytest.approx(original)
    assert road[:, :2] == pytest.approx(camera_path[:, :2])
    assert road[:, 2] == pytest.approx(camera_path[:, 2] - 1.4)
    with pytest.raises(ValueError, match="camera height"):
        road_centerline_from_camera_path(camera_path, 0.1)


def test_opendrive_reference_offset_does_not_move_observed_driving_route() -> None:
    lane = np.array([[0.0, 0.0, -1.4], [5.0, 0.0, -1.4], [10.0, 1.0, -1.4]])
    observed = lane.copy()
    reference = offset_reference_line_from_lane_center(lane, 1.75)
    assert lane == pytest.approx(observed)
    assert reference.shape == lane.shape
    assert np.all(np.isfinite(reference))
    assert np.linalg.norm(reference[:, :2] - lane[:, :2], axis=1) == pytest.approx(
        np.full(3, 1.75)
    )
    assert inferred_reference_offset_for_driving_lane(3.5, "right") == -1.75
    assert inferred_reference_offset_for_driving_lane(3.5, "left") == 1.75


def test_road_endpoint_padding_preserves_observed_route_and_extrapolates_grade() -> None:
    reference = np.array([[0.0, 0.0, -1.4], [5.0, 0.0, -1.9], [10.0, 1.0, -2.4]])
    original = reference.copy()
    padded = extend_road_reference_endpoints(reference, 6.0)
    assert reference == pytest.approx(original)
    assert padded[1:-1] == pytest.approx(reference)
    assert np.linalg.norm(padded[0, :2] - reference[0, :2]) == pytest.approx(6.0)
    assert np.linalg.norm(padded[-1, :2] - reference[-1, :2]) == pytest.approx(6.0)


def test_carla_to_opendrive_flips_only_lateral_axis() -> None:
    carla_points = np.array([[1.0, 2.0, 3.0], [4.0, -5.0, 6.0]])
    original = carla_points.copy()
    opendrive = carla_centerline_to_opendrive(carla_points)
    assert carla_points == pytest.approx(original)
    assert opendrive == pytest.approx(np.array([[1.0, -2.0, 3.0], [4.0, 5.0, 6.0]]))


def test_opendrive_generation_and_invalid_path(tmp_path: Path) -> None:
    path = tmp_path / "map.xodr"
    xml = generate_single_corridor_opendrive(
        np.array([[0.0, 0.0, 0.0], [8.0, 0.0, 0.0], [16.0, 1.0, 0.0]]),
        path,
        lane_width_m=3.5,
        shoulder_width_m=0.5,
        driving_side="right",
        include_opposing_lane=False,
    )
    assert "OpenDRIVE" in xml
    result = validate_opendrive(path)
    assert result.valid and result.road_count == 1 and result.driving_lane_count == 1
    invalid = tmp_path / "invalid.xodr"
    invalid.write_text("<not-opendrive />", encoding="utf-8")
    assert not validate_opendrive(invalid).valid


def test_route_progress_lateral_error_and_infrastructure_classification() -> None:
    metrics = route_metrics([(0, 0, 0), (10, 0, 0), (20, 0, 0)], (5, 2, 0))
    assert metrics.progress == pytest.approx(0.25)
    assert metrics.lateral_error_m == pytest.approx(2.0)
    elevated = route_metrics([(0, 0, -20), (10, 0, -30)], (5, 1, 0))
    assert elevated.lateral_error_m == pytest.approx(1.0)
    assert classify_infrastructure_invalid("sensor desynchronization at frame 9")
    assert not classify_infrastructure_invalid("vehicle collided with a wall")


def test_sensor_barrier_exact_stale_and_timeout() -> None:
    barrier = SensorBarrier(("front", "imu"))
    barrier.push("front", 4, b"old")
    barrier.push("front", 5, b"rgb")
    barrier.push("imu", 5, {"ax": 1})
    assert barrier.collect_exact_frame(5) == {"front": b"rgb", "imu": {"ax": 1}}
    assert barrier.stale_discard_count == 1
    with pytest.raises(SensorSynchronizationError, match="missing exact sensor frames"):
        barrier.collect_exact_frame(6, timeout_s=0.001)


def test_action_guard_emergency_brakes_invalid_and_stale_controls() -> None:
    guard = ActionSafetyGuard()
    valid = guard.validate_control(DirectVehicleControl(steer=0.2, throttle=0.4, brake=0), observation_frame=10, current_frame=10, inference_latency_ms=5, deadline_ms=80)
    assert valid.valid and not valid.emergency_braking
    stale = guard.validate_control(DirectVehicleControl(steer=0.2, throttle=0.4, brake=0), observation_frame=1, current_frame=10, inference_latency_ms=5, deadline_ms=80)
    assert not stale.valid and stale.control.brake == 1.0 and stale.control.throttle == 0.0


def test_action_guard_clamps_fresh_finite_steering_slew_without_parking_vehicle() -> None:
    guard = ActionSafetyGuard(maximum_steering_slew_per_step=0.35)
    result = guard.validate_control(
        DirectVehicleControl(steer=0.8, throttle=0.4, brake=0.0),
        observation_frame=10,
        current_frame=10,
        inference_latency_ms=5.0,
        deadline_ms=80.0,
    )
    assert result.valid
    assert not result.emergency_braking
    assert result.control.steer == pytest.approx(0.35)
    assert result.control.throttle == pytest.approx(0.4)
    assert result.errors == ("steering slew clamped",)


def test_pure_pursuit_converts_left_positive_trajectory_to_carla_negative_steer() -> None:
    controller = PurePursuitPidController()
    left = controller.control(
        TrajectoryAction(
            waypoints=(
                TrajectoryWaypoint(time_offset_s=1.0, x_forward_m=4.0, y_left_m=1.0),
                TrajectoryWaypoint(time_offset_s=2.0, x_forward_m=8.0, y_left_m=2.0),
            ),
            desired_speed_mps=4.0,
            confidence=1.0,
        ),
        speed_mps=0.0,
        delta_seconds=1.0,
    )
    controller.reset()
    right = controller.control(
        TrajectoryAction(
            waypoints=(
                TrajectoryWaypoint(time_offset_s=1.0, x_forward_m=4.0, y_left_m=-1.0),
                TrajectoryWaypoint(time_offset_s=2.0, x_forward_m=8.0, y_left_m=-2.0),
            ),
            desired_speed_mps=4.0,
            confidence=1.0,
        ),
        speed_mps=0.0,
        delta_seconds=1.0,
    )
    assert left.steer < 0.0
    assert right.steer > 0.0
    assert left.throttle == pytest.approx(0.45)


def test_route_corridor_guard_is_explicit_and_only_activates_outside_envelope() -> None:
    raw = TrajectoryAction(
        waypoints=(
            TrajectoryWaypoint(time_offset_s=1.0, x_forward_m=4.0, y_left_m=-1.0),
            TrajectoryWaypoint(time_offset_s=2.0, x_forward_m=8.0, y_left_m=-2.0),
        ),
        desired_speed_mps=4.0,
        confidence=0.8,
    )
    unchanged, active = _route_corridor_guard(raw, (6.0, 0.5, 0.0), 0.55)
    assert not active and unchanged == raw
    guarded, active = _route_corridor_guard(raw, (6.0, 1.5, 0.0), 0.56)
    assert active
    assert guarded.desired_speed_mps == pytest.approx(2.5)
    assert guarded.waypoints[-1].y_left_m == pytest.approx(1.5)


def test_route_stabilizer_progressively_takes_authority_and_limits_speed() -> None:
    policy = DirectVehicleControl(steer=0.2, throttle=0.45, brake=0.0)
    centered, centered_weight = _route_stabilized_control(policy, -0.4, 0.12, 2.0)
    assert centered == policy
    assert centered_weight == pytest.approx(0.0)
    guarded, guarded_weight = _route_stabilized_control(policy, -0.4, 0.40, 3.5)
    assert guarded_weight == pytest.approx(1.0)
    assert guarded.steer == pytest.approx(-0.4)
    assert guarded.throttle == 0.0
    assert guarded.brake > 0.0


def test_route_target_converts_carla_right_positive_axis_to_left_positive() -> None:
    vehicle = SimpleNamespace(
        location=SimpleNamespace(x=0.0, y=0.0, z=0.0),
        rotation=SimpleNamespace(yaw=0.0),
    )
    # At CARLA yaw zero, world -Y is vehicle-left and +Y is vehicle-right.
    left = _route_target_ego(vehicle, [(0.0, 0.0, 0.0), (5.0, -1.0, 0.0)], 0, lookahead=1)
    right = _route_target_ego(vehicle, [(0.0, 0.0, 0.0), (5.0, 1.0, 0.0)], 0, lookahead=1)
    assert left == pytest.approx((5.0, 1.0, 0.0))
    assert right == pytest.approx((5.0, -1.0, 0.0))


def test_snow_condition_changes_real_vehicle_tyre_friction() -> None:
    wheels = [SimpleNamespace(tire_friction=2.0) for _ in range(4)]
    physics = SimpleNamespace(wheels=wheels)

    class Vehicle:
        applied = None

        def get_physics_control(self):
            return physics

        def apply_physics_control(self, value):
            self.applied = value

    vehicle = Vehicle()
    receipt = _configure_vehicle_weather_physics(vehicle, "snow")
    assert vehicle.applied is physics
    assert receipt["tyre_friction_multiplier"] == pytest.approx(0.42)
    assert [wheel.tire_friction for wheel in wheels] == pytest.approx([0.84] * 4)
    assert receipt["snow_mass_ground_truth"] is False


def test_snow_accumulation_scales_real_vehicle_friction_continuously() -> None:
    wheels = [SimpleNamespace(tire_friction=2.0) for _ in range(4)]
    physics = SimpleNamespace(wheels=wheels)

    class Vehicle:
        def get_physics_control(self):
            return physics

        def apply_physics_control(self, value):
            assert value is physics

    receipt = _configure_vehicle_weather_physics(Vehicle(), "snow", 0.5)
    assert receipt["snow_accumulation"] == pytest.approx(0.5)
    assert receipt["tyre_friction_multiplier"] == pytest.approx(0.71)
    assert [wheel.tire_friction for wheel in wheels] == pytest.approx([1.42] * 4)


def test_ground_contact_configuration_enables_and_verifies_swept_wheels() -> None:
    physics = SimpleNamespace(
        use_sweep_wheel_collision=False,
        mass=1840.0,
        drag_coefficient=0.3,
        center_of_mass=SimpleNamespace(x=0.0, y=0.0, z=-0.25),
        wheels=[SimpleNamespace() for _ in range(4)],
    )

    class Vehicle:
        def get_physics_control(self):
            return physics

        def apply_physics_control(self, value):
            assert value is physics

    receipt = _configure_ground_contact_physics(Vehicle())
    assert receipt["sweep_wheel_collision_after"] is True
    assert receipt["mass_kg"] == pytest.approx(1840.0)
    assert receipt["wheel_count"] == 4
    assert receipt["autopilot"] is False


def test_route_goal_accepts_controlled_stop_inside_behavior_agent_tolerance() -> None:
    assert _route_goal_reached(0.995, 2.5, 3.0)
    assert _route_goal_reached(0.91, 2.7, 0.01)
    assert not _route_goal_reached(0.91, 2.7, 2.0)
    assert not _route_goal_reached(0.89, 2.0, 0.0)
    assert not _route_goal_reached(0.99, 3.1, 0.0)


def test_gaussian_snow_deposits_only_on_supported_up_facing_surfaces() -> None:
    gaussians = {
        "means": torch.zeros((3, 3)),
        "scales": torch.tensor(
            [[0.1, 1.0, 1.0], [1.0, 1.0, 0.1], [1.0, 1.0, 1.0]],
            dtype=torch.float32,
        ),
        "quats": torch.tensor(
            [[1.0, 0.0, 0.0, 0.0]] * 3, dtype=torch.float32
        ),
        "colors": torch.cat(
            (torch.zeros((3, 1, 3)), torch.ones((3, 3, 3))), dim=1
        ),
    }
    original = gaussians["colors"].clone()
    stats = ServoGaussianObservationRenderer.apply_surface_snow(
        gaussians, np.asarray([1.0, 0.0, 0.0], dtype=np.float32), 1.0
    )
    assert stats["affected_fraction"] == pytest.approx(1.0 / 3.0)
    assert torch.all(gaussians["colors"][0, 0] > original[0, 0])
    assert torch.all(gaussians["colors"][0, 1:] < original[0, 1:])
    assert torch.equal(gaussians["colors"][1], original[1])
    assert torch.equal(gaussians["colors"][2], original[2])


def test_tinydrive_forward_pass_and_checkpoint_identity(tmp_path: Path) -> None:
    model = ServoTinyDriveNetwork()
    waypoints, speed = model(torch.zeros(2, 9, 48, 80), torch.zeros(2, 8))
    assert waypoints.shape == (2, 5, 2)
    assert speed.shape == (2,) and torch.all(torch.isfinite(speed))
    first = create_initial_checkpoint(tmp_path / "a.pt", seed=1)
    second = create_initial_checkpoint(tmp_path / "b.pt", seed=2)
    assert first != second


def test_dataset_hidden_seed_isolation_and_seal(tmp_path: Path) -> None:
    sample = tmp_path / "sample.npz"
    np.savez(sample, frames=np.zeros((9, 8, 8), np.uint8), auxiliary=np.zeros(8), waypoints=np.zeros((5, 2)), desired_speed=np.array(2.0))
    manifest = seal_dataset_manifest(tmp_path / "dataset.json", observation_source="servo-gaussian", expert_source="carla-behavior-reference", training_seeds=[1, 2], hidden_seeds=[9], route_hashes=["sha256:" + "a" * 64], sample_files=[sample], augmentation={})
    assert manifest["content_hash"].startswith("sha256:")
    with pytest.raises(ValueError, match="hidden seeds leaked"):
        seal_dataset_manifest(tmp_path / "bad.json", observation_source="servo-gaussian", expert_source="oracle", training_seeds=[1], hidden_seeds=[1], route_hashes=[], sample_files=[sample], augmentation={})


def test_session_legal_transitions_commands_and_monotonic_events(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, "sim-0123456789abcdef")
    store.session_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(store.state_path, {"state": "created"})
    store.transition(SimulationSessionState.PREFLIGHTING, "checking runtime")
    assert store.state() is SimulationSessionState.PREFLIGHTING
    with pytest.raises(SimulationTransitionError):
        store.transition(SimulationSessionState.COMPLETED)
    store.command("pause")
    store.command("resume")
    assert store.read_command() == {"command": "resume", "sequence": 2}
    assert [event.sequence for event in store.events.events()] == [1]
    store.events.path.write_text(store.events.path.read_text(encoding="utf-8") + json.dumps({"schema_name": "servo.simulation-event/v1", "sequence": 3, "session_id": store.session_id, "event_type": "bad", "created_at": "2026-01-01T00:00:00Z", "payload": {}}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="non-monotonic"):
        store.events.events()


def test_api_rejects_unknown_runtime_fields() -> None:
    response = TestClient(app).post("/v1/carla/preflight", json={"rpc_port": 2000, "invented": True})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_api_rejects_world_path_outside_registered_roots(tmp_path: Path, monkeypatch) -> None:
    import cloud.control_api.app.main as api

    outside = tmp_path / "unregistered-world"
    outside.mkdir()
    monkeypatch.setattr(api, "SIMULATION_ROOT", tmp_path / "simulation-root")
    monkeypatch.setenv("SERVO_WORLD_ROOTS", "")
    response = TestClient(app).post(
        "/v1/worlds/prepare-carla",
        json={
            "world_path": str(outside),
            "meters_per_servo_unit": 1.0,
            "scale_status": "inferred",
            "scale_source": "test anchor",
            "scale_uncertainty_fraction": 0.1,
        },
    )
    assert response.status_code == 400
    assert "outside validated Servo roots" in response.json()["error"]["message"]


def test_driving_campaign_counterfactuals_and_hidden_curriculum(tmp_path: Path) -> None:
    names = {arm.name for arm in required_counterfactual_arms(2)}
    assert {"oracle-reference", "carla-rgb", "servo-gaussian", "zero-policy-latency", "oracle-controller", "clear-weather", "no-dynamic-actors"} == names
    record = seal_recovery_curriculum(
        tmp_path / "curriculum.json",
        established_cause="visual-domain-failure",
        training_seeds=[1, 2, 3],
        hidden_seeds=[101, 102],
        route_sha256="sha256:" + "b" * 64,
    )
    assert "hidden_seeds" not in record
    assert record["content_hash"].startswith("sha256:")
    with pytest.raises(ValueError, match="hidden seeds leaked"):
        seal_recovery_curriculum(
            tmp_path / "bad-curriculum.json",
            established_cause="control",
            training_seeds=[1],
            hidden_seeds=[1],
            route_sha256="sha256:" + "b" * 64,
        )


def test_hybrid_compositor_requires_exact_synchronized_dynamic_frames() -> None:
    intrinsics = CameraIntrinsics(width=16, height=16, horizontal_fov_deg=90, fx=8, fy=8, cx=7.5, cy=7.5)
    pose = Pose(position=Vector3(x=0, y=0, z=0), orientation=Quaternion(w=1, x=0, y=0, z=0))

    class GaussianStub(ObservationRenderer):
        @property
        def source(self):
            return ObservationSource.SERVO_GAUSSIAN

        def render(self, request):
            return ObservationRenderResult(
                frame_id=request.frame_id,
                rgb=np.zeros((16, 16, 3), dtype=np.uint8),
                intrinsics=intrinsics,
                camera_pose=pose,
                source=self.source,
                source_hashes=("sha256:" + "a" * 64,),
                render_latency_ms=1.0,
                coverage_score=1.0,
                expected_depth=np.full((16, 16), 10.0, dtype=np.float32),
                support_map=np.ones((16, 16), dtype=np.float32),
            )

    renderer = HybridGaussianCarlaObservationRenderer(GaussianStub(), {10}, meters_per_servo_unit=2.0)
    request = ObservationRenderRequest(7, pose, intrinsics)
    with pytest.raises(RuntimeError, match="exact hybrid actor frames"):
        renderer.render(request)
    actor_rgb = np.full((16, 16, 3), 200, dtype=np.uint8)
    renderer.supply_exact_frames(7, actor_rgb, np.full((16, 16), 5.0, np.float32), np.full((16, 16), 10, np.int32))
    result = renderer.render(request)
    assert result.source is ObservationSource.HYBRID
    assert np.all(result.rgb == 200)
