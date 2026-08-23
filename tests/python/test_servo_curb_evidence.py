from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


REPOSITORY = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_curb_evidence.py"
SPEC = importlib.util.spec_from_file_location("servo_curb_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
servo_curb_evidence = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = servo_curb_evidence
SPEC.loader.exec_module(servo_curb_evidence)


FORWARD = (0.0, 1.0, 0.0)
OUTWARD = (1.0, 0.0, 0.0)
UP = (0.0, 0.0, 1.0)


def provenance(
    *,
    metric: bool = False,
    generated: bool = False,
) -> servo_curb_evidence.CurbEvidenceProvenance:
    return servo_curb_evidence.CurbEvidenceProvenance(
        sequence_id="synthetic-road-boundary-sequence",
        coordinate_frame_id="sfm-road-fixture-1",
        scale_provenance="metric-anchored" if metric else "sfm-arbitrary-scale",
        camera_source="synthetic calibrated pinhole cameras",
        depth_source="synthetic camera-Z depth aligned to SfM",
        normal_source="synthetic SfM-frame surface normals",
        semantic_source="synthetic broad road semantics",
        profile_source="synthetic observed cross-road profiles",
        contains_generated_pixels=generated,
        world_units_per_metre=10.0 if metric else None,
        scale_anchor_source="surveyed fixture bar" if metric else None,
        source_hashes=(("fixture", "sha256:" + "a" * 64),),
    )


def boundary_frame(
    frame_index: int,
    camera_x: float,
    kind: str,
    *,
    edge_shift: float = 0.0,
) -> servo_curb_evidence.CalibratedBoundaryFrame:
    profiles = 7
    samples = 10
    points = np.zeros((profiles, samples, 3), dtype=np.float64)
    normals = np.zeros_like(points)
    labels = np.zeros((profiles, samples), dtype=np.int16)
    observed = np.ones((profiles, samples), dtype=bool)
    confidence = np.full((profiles, samples), 0.98, dtype=np.float64)
    pixels = np.zeros((profiles, samples, 2), dtype=np.float64)

    for profile in range(profiles):
        along = (profile - (profiles - 1) * 0.5) * 0.5
        if kind in {"step", "occluded", "stacked"}:
            outward = np.asarray(
                [-0.4, -0.3, -0.2, -0.1, 0.0, 0.0, 0.0, 0.1, 0.2, 0.3]
            ) + edge_shift
            height = np.asarray(
                [0.0, 0.0, 0.0, 0.0, 0.03, 0.09, 0.14, 0.15, 0.15, 0.15]
            )
            points[profile, :, 0] = outward
            points[profile, :, 1] = along
            points[profile, :, 2] = height
            normals[profile, :4, 2] = 1.0
            normals[profile, 4:7, 0] = 1.0
            normals[profile, 7:, 2] = 1.0
            labels[profile, :4] = 1  # Broad road support.
            labels[profile, 4:7] = 3  # Semantic curb proposal, not sufficient alone.
            labels[profile, 7:] = 4  # Sidewalk/top surface.
            if kind == "occluded":
                observed[profile, 3:8] = False
            elif kind == "stacked":
                labels[profile, 7:] = 1  # A second road run/layer.
        elif kind in {"flat-paint-edge", "flat-road-edge"}:
            points[profile, :, 0] = np.linspace(-0.4, 0.5, samples) + edge_shift
            points[profile, :, 1] = along
            normals[profile, :, 2] = 1.0
            labels[profile, :] = 1
            labels[profile, 4] = 2  # Paint stays part of road support.
            if kind == "flat-road-edge":
                labels[profile, 5:] = 0
        elif kind == "sloped-bank":
            points[profile, :, 0] = np.linspace(-0.4, 0.5, samples) + edge_shift
            points[profile, :, 1] = along
            points[profile, 5:, 2] = np.linspace(0.04, 0.20, 5)
            normals[profile, :5, 2] = 1.0
            bank_normal = np.asarray((-0.4, 0.0, 1.0), dtype=np.float64)
            bank_normal /= np.linalg.norm(bank_normal)
            normals[profile, 5:] = bank_normal
            labels[profile, :5] = 1
            labels[profile, 5:] = 6  # Soft terrain/shoulder evidence.
        else:
            raise AssertionError(f"unknown fixture kind {kind}")

    calibration = np.asarray(
        [[120.0, 0.0, 128.0], [0.0, 120.0, 96.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    camera_to_world = np.eye(4, dtype=np.float64)
    camera_to_world[0, 3] = camera_x
    camera_to_world[2, 3] = -5.0
    camera_points = points - camera_to_world[:3, 3]
    projected = (calibration @ camera_points.reshape(-1, 3).T).T
    pixels[:] = (projected[:, :2] / projected[:, 2, None]).reshape(
        profiles, samples, 2
    )
    return servo_curb_evidence.CalibratedBoundaryFrame(
        frame_id=f"frame-{frame_index:04d}",
        frame_index=frame_index,
        image_size=(256, 192),
        calibration=calibration,
        camera_to_world=camera_to_world,
        profile_points_world=points,
        profile_normals_world=normals,
        semantic_labels=labels,
        observed_mask=observed,
        source_pixels_xy=pixels,
        confidence=confidence,
    )


def three_views(
    kind: str,
    *,
    edge_shifts: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> list[servo_curb_evidence.CalibratedBoundaryFrame]:
    return [
        boundary_frame(frame_index, camera_x, kind, edge_shift=edge_shift)
        for frame_index, camera_x, edge_shift in zip(
            (0, 2, 4), (-0.6, 0.0, 0.6), edge_shifts
        )
    ]


def build(
    frames: list[servo_curb_evidence.CalibratedBoundaryFrame],
    *,
    evidence_provenance: servo_curb_evidence.CurbEvidenceProvenance | None = None,
) -> servo_curb_evidence.CurbEvidenceBundle:
    return servo_curb_evidence.build_curb_evidence(
        frames,
        evidence_provenance or provenance(),
        boundary_id="right-boundary-001",
        forward_axis_world=FORWARD,
        outward_axis_world=OUTWARD,
        up_axis_world=UP,
    )


class ServoCurbEvidenceTests(unittest.TestCase):
    def test_flat_paint_edge_is_not_promoted_to_curb(self) -> None:
        bundle = build(three_views("flat-paint-edge"))
        self.assertEqual(
            bundle.classification, servo_curb_evidence.BoundaryClass.UNKNOWN
        )
        self.assertEqual(bundle.edge_evidence_points_world, ())
        self.assertIsNone(bundle.step_height_world_units)
        self.assertIsNone(bundle.step_height_metres)
        self.assertFalse(bundle.metrics()["metricHeightClaim"])
        self.assertFalse(bundle.metrics()["containsGeneratedPixels"])

    def test_repeated_flat_semantic_boundary_is_road_edge_not_curb(self) -> None:
        bundle = build(three_views("flat-road-edge"))
        self.assertEqual(
            bundle.classification, servo_curb_evidence.BoundaryClass.ROAD_EDGE
        )
        self.assertIsNone(bundle.step_height_world_units)

    def test_repeated_vertical_step_and_face_verify_curb_geometry(self) -> None:
        frames = three_views("step")
        bundle = build(frames)
        self.assertEqual(
            bundle.classification, servo_curb_evidence.BoundaryClass.CURB
        )
        self.assertAlmostEqual(bundle.step_height_world_units or 0.0, 0.15)
        self.assertIsNone(bundle.step_height_metres)
        self.assertEqual(bundle.selected_frame_ids, tuple(item.frame_id for item in frames))
        self.assertEqual(len(bundle.edge_evidence_points_world), 21)
        source_points = {
            tuple(float(value) for value in point)
            for frame in frames
            for point in frame.profile_points_world.reshape(-1, 3)
        }
        self.assertTrue(set(bundle.edge_evidence_points_world).issubset(source_points))
        self.assertTrue(
            all(
                profile.face_sample_count >= 2
                for view in bundle.views
                for profile in view.profiles
                if profile.classification
                is servo_curb_evidence.BoundaryClass.CURB
            )
        )

    def test_sloped_bank_is_soft_shoulder_not_curb(self) -> None:
        bundle = build(three_views("sloped-bank"))
        self.assertEqual(
            bundle.classification, servo_curb_evidence.BoundaryClass.SHOULDER
        )
        self.assertIsNone(bundle.step_height_world_units)

    def test_occluded_transition_fails_closed(self) -> None:
        bundle = build(three_views("occluded"))
        self.assertEqual(
            bundle.classification, servo_curb_evidence.BoundaryClass.UNKNOWN
        )
        self.assertIn("insufficient-separated-views", bundle.reasons)
        self.assertEqual(bundle.edge_evidence_points_world, ())

    def test_stacked_road_surfaces_fail_closed(self) -> None:
        bundle = build(three_views("stacked"))
        self.assertEqual(
            bundle.classification, servo_curb_evidence.BoundaryClass.UNKNOWN
        )
        self.assertEqual(bundle.reasons, ("stacked-road-evidence",))

    def test_insufficient_views_fail_closed(self) -> None:
        bundle = build(three_views("step")[:2])
        self.assertEqual(
            bundle.classification, servo_curb_evidence.BoundaryClass.UNKNOWN
        )
        self.assertIn("insufficient-separated-views", bundle.reasons)

    def test_inconsistent_multi_view_edge_location_fails_closed(self) -> None:
        bundle = build(three_views("step", edge_shifts=(0.0, 0.0, 0.8)))
        self.assertEqual(
            bundle.classification, servo_curb_evidence.BoundaryClass.UNKNOWN
        )
        self.assertIn("multi-view-edge-location-is-inconsistent", bundle.reasons)

    def test_duplicate_camera_pose_is_not_independent_multi_view_evidence(self) -> None:
        frames = [
            boundary_frame(frame_index, 0.0, "step")
            for frame_index in (0, 2, 4)
        ]
        bundle = build(frames)
        self.assertEqual(
            bundle.classification, servo_curb_evidence.BoundaryClass.UNKNOWN
        )
        self.assertIn("calibrated-view-baseline-is-insufficient", bundle.reasons)

    def test_one_inconsistent_step_height_view_fails_closed(self) -> None:
        frames = three_views("step")
        outlier = frames[-1]
        points = np.asarray(outlier.profile_points_world).copy()
        points[..., 2] *= 3.0
        transform = np.asarray(outlier.camera_to_world)
        camera_points = (
            transform[:3, :3].T
            @ (points.reshape(-1, 3) - transform[:3, 3]).T
        ).T
        projected = (np.asarray(outlier.calibration) @ camera_points.T).T
        pixels = (projected[:, :2] / projected[:, 2, None]).reshape(
            outlier.source_pixels_xy.shape
        )
        frames[-1] = servo_curb_evidence.CalibratedBoundaryFrame(
            **{
                **outlier.__dict__,
                "profile_points_world": points,
                "source_pixels_xy": pixels,
            }
        )
        bundle = build(frames)
        self.assertEqual(
            bundle.classification, servo_curb_evidence.BoundaryClass.UNKNOWN
        )
        self.assertIn("multi-view-step-height-is-inconsistent", bundle.reasons)

    def test_discontinuous_step_profiles_do_not_form_a_curb(self) -> None:
        damaged = []
        for frame in three_views("step"):
            points = np.asarray(frame.profile_points_world).copy()
            points[3, :, 1] += 2.0
            camera_to_world = np.asarray(frame.camera_to_world)
            rotation = camera_to_world[:3, :3]
            camera_points = (
                rotation.T
                @ (points.reshape(-1, 3) - camera_to_world[:3, 3]).T
            ).T
            projected = (np.asarray(frame.calibration) @ camera_points.T).T
            pixels = (projected[:, :2] / projected[:, 2, None]).reshape(
                frame.source_pixels_xy.shape
            )
            damaged.append(
                servo_curb_evidence.CalibratedBoundaryFrame(
                    **{
                        **frame.__dict__,
                        "profile_points_world": points,
                        "source_pixels_xy": pixels,
                    }
                )
            )
        bundle = build(damaged)
        self.assertEqual(
            bundle.classification, servo_curb_evidence.BoundaryClass.UNKNOWN
        )
        self.assertTrue(
            all(
                "boundary-world-geometry-is-discontinuous" in view.reasons
                for view in bundle.views
            )
        )

    def test_arbitrary_scale_never_claims_metric_height(self) -> None:
        bundle = build(three_views("step"), evidence_provenance=provenance())
        self.assertEqual(
            bundle.classification, servo_curb_evidence.BoundaryClass.CURB
        )
        self.assertIsNone(bundle.step_height_metres)
        self.assertFalse(bundle.metrics()["metricHeightClaim"])
        self.assertIsNone(bundle.manifest()["summary"]["stepHeightMetres"])

    def test_metric_height_requires_an_explicit_scale_anchor(self) -> None:
        bundle = build(
            three_views("step"), evidence_provenance=provenance(metric=True)
        )
        self.assertAlmostEqual(bundle.step_height_metres or 0.0, 0.015)
        self.assertTrue(bundle.metrics()["metricHeightClaim"])

        malformed = provenance(metric=True)
        malformed = servo_curb_evidence.CurbEvidenceProvenance(
            **{
                **malformed.__dict__,
                "scale_anchor_source": None,
            }
        )
        with self.assertRaises(servo_curb_evidence.CurbEvidenceError):
            build(three_views("step"), evidence_provenance=malformed)

    def test_generated_pixels_are_rejected_and_manifest_is_deterministic(self) -> None:
        frames = three_views("step")
        first = build(frames)
        second = build(frames)
        self.assertEqual(first.canonical_manifest_json(), second.canonical_manifest_json())
        self.assertEqual(first.manifest_sha256(), second.manifest_sha256())
        self.assertFalse(first.manifest()["safety"]["containsGeneratedPixels"])
        with self.assertRaises(servo_curb_evidence.CurbEvidenceError):
            build(frames, evidence_provenance=provenance(generated=True))

    def test_points_must_reproject_to_the_claimed_source_pixels(self) -> None:
        frame = boundary_frame(0, -0.6, "step")
        bad_pixels = np.asarray(frame.source_pixels_xy).copy()
        bad_pixels[..., 0] += 4.0
        malformed = servo_curb_evidence.CalibratedBoundaryFrame(
            **{
                **frame.__dict__,
                "source_pixels_xy": bad_pixels,
            }
        )
        with self.assertRaisesRegex(
            servo_curb_evidence.CurbEvidenceError, "reproject"
        ):
            build([malformed, *three_views("step")[1:]])

    def test_camera_z_depth_unprojects_to_the_same_observed_world_geometry(self) -> None:
        converted = []
        for frame in three_views("step"):
            transform = np.asarray(frame.camera_to_world)
            rotation = transform[:3, :3]
            points_camera = (
                rotation.T
                @ (
                    frame.profile_points_world.reshape(-1, 3)
                    - transform[:3, 3]
                ).T
            ).T.reshape(frame.profile_points_world.shape)
            normals_camera = frame.profile_normals_world @ rotation
            converted.append(
                servo_curb_evidence.frame_from_camera_z_depth(
                    frame_id=frame.frame_id,
                    frame_index=frame.frame_index,
                    image_size=frame.image_size,
                    calibration=frame.calibration,
                    camera_to_world=frame.camera_to_world,
                    profile_depth_camera_z=points_camera[..., 2],
                    profile_normals_camera=normals_camera,
                    semantic_labels=frame.semantic_labels,
                    observed_mask=frame.observed_mask,
                    source_pixels_xy=frame.source_pixels_xy,
                    confidence=frame.confidence,
                )
            )
            np.testing.assert_allclose(
                converted[-1].profile_points_world,
                frame.profile_points_world,
                atol=1.0e-12,
            )
        self.assertEqual(
            build(converted).classification,
            servo_curb_evidence.BoundaryClass.CURB,
        )


if __name__ == "__main__":
    unittest.main()
