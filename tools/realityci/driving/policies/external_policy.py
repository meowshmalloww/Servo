"""Versioned, deadline-bounded local HTTP boundary for future driving policies."""

from __future__ import annotations

import json
import base64
import urllib.error
import urllib.request

from ...schemas.driving import DrivingPolicyDescriptor, TrajectoryAction
from ..contracts import DrivingObservation, DrivingPolicyAdapter, PolicyResetContext


class ExternalDrivingPolicy(DrivingPolicyAdapter):
    def __init__(self, endpoint: str, deadline_ms: float = 80.0, *, name: str = "External local driving policy", input_camera_ids: tuple[str, ...] = ("front",)) -> None:
        if not endpoint.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("external driving policy endpoint must be a local HTTP service")
        self.endpoint, self.deadline_ms = endpoint, deadline_ms
        self._last_provenance: dict = {}
        self._descriptor = DrivingPolicyDescriptor(
            adapter="external-driving", name=name,
            adapter_version="servo.external-driving/v1", trainable=False,
            eligible_for_promotion=False, input_camera_ids=input_camera_ids,
            uses_ego_speed=True, uses_ego_acceleration=True,
            uses_recent_ego_poses=True, uses_previous_action=True,
        )

    @property
    def descriptor(self) -> DrivingPolicyDescriptor:
        return self._descriptor

    def reset(self, context: PolicyResetContext) -> None:
        self._last_provenance = {}
        return None

    @property
    def last_provenance(self) -> dict:
        return dict(self._last_provenance)

    def infer(self, observation: DrivingObservation) -> TrajectoryAction:
        if observation.hidden_seed is not None or observation.privileged_actor_state is not None:
            raise ValueError("external non-oracle policy observation contains privileged fields")
        if set(observation.camera_rgb) != set(self.descriptor.input_camera_ids):
            raise ValueError("external policy camera set does not match its declared contract")
        payload = {
            "schema_name": "servo.external-driving-request/v1",
            "frame_id": observation.frame_id,
            "simulation_time_s": observation.simulation_time_s,
            "ego_speed_mps": observation.ego_speed_mps,
            "ego_acceleration_mps2": observation.ego_acceleration_mps2,
            "recent_ego_poses": observation.recent_ego_poses,
            "route_target_ego_m": observation.route_target_ego_m,
            "navigation_command": observation.navigation_command.value,
            "source": observation.source.value,
            "source_provenance": observation.source_provenance,
            "camera_intrinsics": {
                camera_id: intrinsics.model_dump(mode="json")
                for camera_id, intrinsics in observation.camera_intrinsics.items()
            },
            "camera_frames": {
                camera_id: {
                    "encoding": "rgb8-base64",
                    "shape": list(frame.shape),
                    "data": base64.b64encode(frame.tobytes(order="C")).decode("ascii"),
                }
                for camera_id, frame in observation.camera_rgb.items()
            },
            "previous_action": (
                observation.previous_action.model_dump(mode="json")
                if observation.previous_action is not None else None
            ),
        }
        request = urllib.request.Request(self.endpoint, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.deadline_ms / 1000.0) as response:
                result = json.load(response)
        except (OSError, urllib.error.URLError) as exc:
            raise RuntimeError(f"external policy disconnected or exceeded its deadline: {exc}") from exc
        if result.get("schema_name") != "servo.external-driving-response/v1":
            raise ValueError("external policy returned an unsupported protocol version")
        provenance = result.get("provenance")
        if not isinstance(provenance, dict):
            raise ValueError("external policy response is missing provenance")
        self._last_provenance = provenance
        return TrajectoryAction.model_validate(result["action"])

    def detect_roadside(self, camera_rgb: dict, timeout_s: float = 180.0) -> dict:
        payload = {
            "schema_name": "servo.external-driving-request/v1",
            "camera_frames": {
                camera_id: {
                    "encoding": "rgb8-base64", "shape": list(frame.shape),
                    "data": base64.b64encode(frame.tobytes(order="C")).decode("ascii"),
                }
                for camera_id, frame in camera_rgb.items()
            },
        }
        service_root = self.endpoint.rsplit("/", 1)[0] if self.endpoint.rstrip("/").endswith("/predict") else self.endpoint.rstrip("/")
        request = urllib.request.Request(
            service_root + "/detect", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            result = json.load(response)
        if result.get("schema_name") != "servo.roadside-detection/v1":
            raise ValueError("roadside detector returned an unsupported protocol version")
        return result
