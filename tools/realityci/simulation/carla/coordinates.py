"""Single authoritative Servo/CARLA pose conversion implementation."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ...schemas.driving import Pose, Quaternion, Vector3


def _matrix(values: tuple[float, ...] | list[float]) -> np.ndarray:
    matrix = np.asarray(values, dtype=np.float64).reshape(4, 4)
    if not np.all(np.isfinite(matrix)):
        raise ValueError("coordinate transform contains non-finite values")
    determinant = float(np.linalg.det(matrix))
    if abs(determinant) < 1e-9:
        raise ValueError("coordinate transform is not invertible")
    return matrix


def validate_inverse_pair(carla_from_servo: tuple[float, ...], servo_from_carla: tuple[float, ...], tolerance: float = 1e-6) -> float:
    forward = _matrix(carla_from_servo)
    inverse = _matrix(servo_from_carla)
    error = float(np.max(np.abs(forward @ inverse - np.eye(4))))
    if error > tolerance:
        raise ValueError(f"coordinate matrices are not inverses (max error {error:.3g})")
    return error


def invert_matrix(row_major: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(float(value) for value in np.linalg.inv(_matrix(row_major)).reshape(-1))


def transform_position(matrix: tuple[float, ...], value: Vector3) -> Vector3:
    output = _matrix(matrix) @ np.array([value.x, value.y, value.z, 1.0])
    if abs(output[3]) < 1e-12:
        raise ValueError("coordinate transform produced a point at infinity")
    output = output[:3] / output[3]
    return Vector3(x=float(output[0]), y=float(output[1]), z=float(output[2]))


def transform_direction(matrix: tuple[float, ...], value: Vector3) -> Vector3:
    output = _matrix(matrix) @ np.array([value.x, value.y, value.z, 0.0])
    length = float(np.linalg.norm(output[:3]))
    if length < 1e-12:
        raise ValueError("coordinate transform collapsed a direction")
    output = output[:3] / length
    return Vector3(x=float(output[0]), y=float(output[1]), z=float(output[2]))


def quaternion_to_matrix(value: Quaternion) -> np.ndarray:
    q = np.array([value.w, value.x, value.y, value.z], dtype=np.float64)
    norm = float(np.linalg.norm(q))
    if norm < 1e-12 or not math.isfinite(norm):
        raise ValueError("orientation quaternion is invalid")
    w, x, y, z = q / norm
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def matrix_to_quaternion(matrix: np.ndarray) -> Quaternion:
    matrix = np.asarray(matrix, dtype=np.float64).reshape(3, 3)
    u, _, vt = np.linalg.svd(matrix)
    matrix = u @ vt
    if np.linalg.det(matrix) < 0:
        u[:, -1] *= -1
        matrix = u @ vt
    trace = float(np.trace(matrix))
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        w, x, y, z = 0.25 * s, (matrix[2, 1] - matrix[1, 2]) / s, (matrix[0, 2] - matrix[2, 0]) / s, (matrix[1, 0] - matrix[0, 1]) / s
    else:
        index = int(np.argmax(np.diag(matrix)))
        if index == 0:
            s = math.sqrt(1.0 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2]) * 2
            w, x, y, z = (matrix[2, 1] - matrix[1, 2]) / s, 0.25 * s, (matrix[0, 1] + matrix[1, 0]) / s, (matrix[0, 2] + matrix[2, 0]) / s
        elif index == 1:
            s = math.sqrt(1.0 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2]) * 2
            w, x, y, z = (matrix[0, 2] - matrix[2, 0]) / s, (matrix[0, 1] + matrix[1, 0]) / s, 0.25 * s, (matrix[1, 2] + matrix[2, 1]) / s
        else:
            s = math.sqrt(1.0 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1]) * 2
            w, x, y, z = (matrix[1, 0] - matrix[0, 1]) / s, (matrix[0, 2] + matrix[2, 0]) / s, (matrix[1, 2] + matrix[2, 1]) / s, 0.25 * s
    if w < 0:
        w, x, y, z = -w, -x, -y, -z
    return Quaternion(w=w, x=x, y=y, z=z)


def transform_orientation(matrix: tuple[float, ...], orientation: Quaternion) -> Quaternion:
    axes = _matrix(matrix)[:3, :3]
    return matrix_to_quaternion(axes @ quaternion_to_matrix(orientation) @ np.linalg.inv(axes))


@dataclass(frozen=True)
class CoordinateTransform:
    carla_from_servo: tuple[float, ...]
    servo_from_carla: tuple[float, ...]

    def __post_init__(self) -> None:
        validate_inverse_pair(self.carla_from_servo, self.servo_from_carla)

    def position_servo_to_carla(self, value: Vector3) -> Vector3:
        return transform_position(self.carla_from_servo, value)

    def position_carla_to_servo(self, value: Vector3) -> Vector3:
        return transform_position(self.servo_from_carla, value)

    def direction_servo_to_carla(self, value: Vector3) -> Vector3:
        return transform_direction(self.carla_from_servo, value)

    def direction_carla_to_servo(self, value: Vector3) -> Vector3:
        return transform_direction(self.servo_from_carla, value)

    def orientation_servo_to_carla(self, value: Quaternion) -> Quaternion:
        return transform_orientation(self.carla_from_servo, value)

    def orientation_carla_to_servo(self, value: Quaternion) -> Quaternion:
        return transform_orientation(self.servo_from_carla, value)

    def pose_servo_to_carla(self, value: Pose) -> Pose:
        return Pose(position=self.position_servo_to_carla(value.position), orientation=self.orientation_servo_to_carla(value.orientation))

    def pose_carla_to_servo(self, value: Pose) -> Pose:
        return Pose(position=self.position_carla_to_servo(value.position), orientation=self.orientation_carla_to_servo(value.orientation))


def default_handedness_matrix(meters_per_servo_unit: float) -> tuple[float, ...]:
    if not math.isfinite(meters_per_servo_unit) or meters_per_servo_unit <= 0:
        raise ValueError("meters_per_servo_unit must be finite and positive")
    # Servo: X right, Y up, -Z forward. CARLA: X forward, Y right, Z up.
    scale = meters_per_servo_unit
    return (
        0.0, 0.0, -scale, 0.0,
        scale, 0.0, 0.0, 0.0,
        0.0, scale, 0.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )
