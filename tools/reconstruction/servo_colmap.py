"""Minimal read-only COLMAP model adapter used by Servo training.

This intentionally implements only the stable cameras/images/points3D binary
and text fields
consumed by ``servo_train.py``. It is not a replacement for COLMAP or pycolmap.
"""

from __future__ import annotations

import dataclasses
import struct
from pathlib import Path
from typing import BinaryIO

import numpy as np


class ColmapFormatError(RuntimeError):
    pass


CAMERA_MODELS: dict[int, tuple[str, int]] = {
    0: ("SIMPLE_PINHOLE", 3),
    1: ("PINHOLE", 4),
    2: ("SIMPLE_RADIAL", 4),
    3: ("RADIAL", 5),
    4: ("OPENCV", 8),
    5: ("OPENCV_FISHEYE", 8),
    6: ("FULL_OPENCV", 12),
    7: ("FOV", 5),
    8: ("SIMPLE_RADIAL_FISHEYE", 4),
    9: ("RADIAL_FISHEYE", 5),
    10: ("THIN_PRISM_FISHEYE", 12),
}


def _read(stream: BinaryIO, layout: str) -> tuple[object, ...]:
    size = struct.calcsize("<" + layout)
    payload = stream.read(size)
    if len(payload) != size:
        raise ColmapFormatError("COLMAP binary model ended unexpectedly.")
    return struct.unpack("<" + layout, payload)


def _read_name(stream: BinaryIO) -> str:
    value = bytearray()
    while True:
        byte = stream.read(1)
        if not byte:
            raise ColmapFormatError("COLMAP image name is unterminated.")
        if byte == b"\0":
            return value.decode("utf-8")
        value.extend(byte)
        if len(value) > 32_768:
            raise ColmapFormatError("COLMAP image name exceeds the safety limit.")


def _rotation_from_qvec(qvec: tuple[float, ...]) -> np.ndarray:
    w, x, y, z = qvec
    norm = np.linalg.norm(qvec)
    if not np.isfinite(norm) or norm <= 1e-12:
        raise ColmapFormatError("COLMAP image has an invalid quaternion.")
    w, x, y, z = (value / norm for value in (w, x, y, z))
    return np.asarray(
        [
            [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * w * z, 2 * x * z + 2 * w * y],
            [2 * x * y + 2 * w * z, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * w * x],
            [2 * x * z - 2 * w * y, 2 * y * z + 2 * w * x, 1 - 2 * x * x - 2 * y * y],
        ],
        dtype=np.float64,
    )


@dataclasses.dataclass(frozen=True)
class Rigid3d:
    value: np.ndarray

    def matrix(self) -> np.ndarray:
        return self.value[:3, :4].copy()

    def inverse(self) -> "Rigid3d":
        return Rigid3d(np.linalg.inv(self.value))


@dataclasses.dataclass(frozen=True)
class Camera:
    camera_id: int
    model_name: str
    width: int
    height: int
    params: tuple[float, ...]

    def calibration_matrix(self) -> np.ndarray:
        if self.model_name == "SIMPLE_PINHOLE":
            focal, cx, cy = self.params
            fx = fy = focal
        elif self.model_name == "PINHOLE":
            fx, fy, cx, cy = self.params
        elif self.model_name in {
            "SIMPLE_RADIAL",
            "RADIAL",
            "SIMPLE_RADIAL_FISHEYE",
            "RADIAL_FISHEYE",
        }:
            focal, cx, cy = self.params[:3]
            fx = fy = focal
        else:
            fx, fy, cx, cy = self.params[:4]
        return np.asarray(
            [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )


@dataclasses.dataclass(frozen=True)
class Point2D:
    xy: np.ndarray
    point3D_id: int

    def has_point3D(self) -> bool:
        return self.point3D_id >= 0


@dataclasses.dataclass(frozen=True)
class Image:
    image_id: int
    camera_id: int
    name: str
    _camera_from_world: Rigid3d
    points2D: tuple[Point2D, ...]

    @property
    def has_pose(self) -> bool:
        return True

    def cam_from_world(self) -> Rigid3d:
        return self._camera_from_world


@dataclasses.dataclass(frozen=True)
class TrackElement:
    image_id: int
    point2D_idx: int


@dataclasses.dataclass(frozen=True)
class Track:
    elements: tuple[TrackElement, ...]

    def length(self) -> int:
        return len(self.elements)


@dataclasses.dataclass(frozen=True)
class Point3D:
    point3D_id: int
    xyz: np.ndarray
    color: np.ndarray
    error: float
    track: Track


class Reconstruction:
    def __init__(self, root: str | Path) -> None:
        root = Path(root)
        binary = all((root / name).is_file() for name in ("cameras.bin", "images.bin", "points3D.bin"))
        text = all((root / name).is_file() for name in ("cameras.txt", "images.txt", "points3D.txt"))
        if binary:
            self.cameras = self._read_cameras(root / "cameras.bin")
            self.images = self._read_images(root / "images.bin")
            self.points3D = self._read_points(root / "points3D.bin")
        elif text:
            self.cameras = self._read_cameras_text(root / "cameras.txt")
            self.images = self._read_images_text(root / "images.txt")
            self.points3D = self._read_points_text(root / "points3D.txt")
        else:
            raise FileNotFoundError(
                f"COLMAP model at {root} must contain a complete binary or text model."
            )
        missing = {
            image.camera_id for image in self.images.values()
        }.difference(self.cameras)
        if missing:
            raise ColmapFormatError(
                "COLMAP images reference missing cameras: "
                + ", ".join(str(value) for value in sorted(missing))
            )

    @staticmethod
    def _read_cameras(path: Path) -> dict[int, Camera]:
        cameras: dict[int, Camera] = {}
        with path.open("rb") as stream:
            count = int(_read(stream, "Q")[0])
            for _ in range(count):
                camera_id, model_id, width, height = _read(stream, "iiQQ")
                if model_id not in CAMERA_MODELS:
                    raise ColmapFormatError(f"Unsupported COLMAP camera model id: {model_id}")
                name, parameter_count = CAMERA_MODELS[int(model_id)]
                params = tuple(float(value) for value in _read(stream, "d" * parameter_count))
                cameras[int(camera_id)] = Camera(
                    int(camera_id), name, int(width), int(height), params
                )
        return cameras

    @staticmethod
    def _read_images(path: Path) -> dict[int, Image]:
        images: dict[int, Image] = {}
        with path.open("rb") as stream:
            count = int(_read(stream, "Q")[0])
            for _ in range(count):
                image_id = int(_read(stream, "i")[0])
                qvec = tuple(float(value) for value in _read(stream, "4d"))
                translation = np.asarray(_read(stream, "3d"), dtype=np.float64)
                camera_id = int(_read(stream, "i")[0])
                name = _read_name(stream)
                point_count = int(_read(stream, "Q")[0])
                points: list[Point2D] = []
                for _ in range(point_count):
                    x, y, point_id = _read(stream, "2dq")
                    points.append(
                        Point2D(
                            np.asarray([x, y], dtype=np.float64), int(point_id)
                        )
                    )
                matrix = np.eye(4, dtype=np.float64)
                matrix[:3, :3] = _rotation_from_qvec(qvec)
                matrix[:3, 3] = translation
                images[image_id] = Image(
                    image_id,
                    camera_id,
                    name,
                    Rigid3d(matrix),
                    tuple(points),
                )
        return images

    @staticmethod
    def _read_points(path: Path) -> dict[int, Point3D]:
        points: dict[int, Point3D] = {}
        with path.open("rb") as stream:
            count = int(_read(stream, "Q")[0])
            for _ in range(count):
                values = _read(stream, "QdddBBBd")
                point_id = int(values[0])
                track_count = int(_read(stream, "Q")[0])
                elements = tuple(
                    TrackElement(*map(int, _read(stream, "ii")))
                    for _ in range(track_count)
                )
                points[point_id] = Point3D(
                    point_id,
                    np.asarray(values[1:4], dtype=np.float64),
                    np.asarray(values[4:7], dtype=np.uint8),
                    float(values[7]),
                    Track(elements),
                )
        return points

    @staticmethod
    def _read_cameras_text(path: Path) -> dict[int, Camera]:
        cameras: dict[int, Camera] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split()
            if len(fields) < 5:
                raise ColmapFormatError(f"Malformed COLMAP camera row: {line}")
            camera_id = int(fields[0])
            model_name = fields[1]
            model = next(
                (item for item in CAMERA_MODELS.values() if item[0] == model_name),
                None,
            )
            if model is None:
                raise ColmapFormatError(f"Unsupported COLMAP camera model: {model_name}")
            parameter_count = model[1]
            if len(fields) != 4 + parameter_count:
                raise ColmapFormatError(
                    f"COLMAP {model_name} camera requires {parameter_count} parameters."
                )
            cameras[camera_id] = Camera(
                camera_id,
                model_name,
                int(fields[2]),
                int(fields[3]),
                tuple(float(value) for value in fields[4:]),
            )
        return cameras

    @staticmethod
    def _read_images_text(path: Path) -> dict[int, Image]:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
        images: dict[int, Image] = {}
        index = 0
        while index < len(raw_lines):
            header = raw_lines[index].strip()
            index += 1
            if not header or header.startswith("#"):
                continue
            fields = header.split()
            if len(fields) < 10:
                raise ColmapFormatError(f"Malformed COLMAP image row: {header}")
            while index < len(raw_lines) and raw_lines[index].lstrip().startswith("#"):
                index += 1
            points_line = raw_lines[index].strip() if index < len(raw_lines) else ""
            index += 1
            point_fields = points_line.split()
            if len(point_fields) % 3:
                raise ColmapFormatError(
                    f"Malformed COLMAP image observations for image {fields[0]}."
                )
            points = tuple(
                Point2D(
                    np.asarray(
                        [float(point_fields[offset]), float(point_fields[offset + 1])],
                        dtype=np.float64,
                    ),
                    int(point_fields[offset + 2]),
                )
                for offset in range(0, len(point_fields), 3)
            )
            matrix = np.eye(4, dtype=np.float64)
            matrix[:3, :3] = _rotation_from_qvec(
                tuple(float(value) for value in fields[1:5])
            )
            matrix[:3, 3] = np.asarray(
                [float(value) for value in fields[5:8]], dtype=np.float64
            )
            image_id = int(fields[0])
            images[image_id] = Image(
                image_id,
                int(fields[8]),
                " ".join(fields[9:]),
                Rigid3d(matrix),
                points,
            )
        return images

    @staticmethod
    def _read_points_text(path: Path) -> dict[int, Point3D]:
        points: dict[int, Point3D] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split()
            if len(fields) < 8 or (len(fields) - 8) % 2:
                raise ColmapFormatError(f"Malformed COLMAP point row: {line}")
            point_id = int(fields[0])
            elements = tuple(
                TrackElement(int(fields[offset]), int(fields[offset + 1]))
                for offset in range(8, len(fields), 2)
            )
            points[point_id] = Point3D(
                point_id,
                np.asarray([float(value) for value in fields[1:4]], dtype=np.float64),
                np.asarray([int(value) for value in fields[4:7]], dtype=np.uint8),
                float(fields[7]),
                Track(elements),
            )
        return points
