from __future__ import annotations

import dataclasses
import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


REPOSITORY = Path(__file__).resolve().parents[2]
GEOMETRY_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_geometry.py"
SPEC = importlib.util.spec_from_file_location("servo_geometry", GEOMETRY_PATH)
assert SPEC is not None and SPEC.loader is not None
servo_geometry = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = servo_geometry
SPEC.loader.exec_module(servo_geometry)

PRIORS_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_priors.py"
PRIORS_SPEC = importlib.util.spec_from_file_location("servo_priors", PRIORS_PATH)
assert PRIORS_SPEC is not None and PRIORS_SPEC.loader is not None
servo_priors = importlib.util.module_from_spec(PRIORS_SPEC)
sys.modules[PRIORS_SPEC.name] = servo_priors
PRIORS_SPEC.loader.exec_module(servo_priors)


def depth_fixture() -> servo_geometry.DepthAlignmentResult:
    relative = np.linspace(0.08, 1.2, 120, dtype=np.float64)
    inverse_sfm = 2.75 * relative + 0.15
    sfm_depth = 1.0 / inverse_sfm
    outliers = np.array([5, 17, 38, 72, 93, 111])
    sfm_depth[outliers] = 1.0 / (inverse_sfm[outliers] + 3.0)
    confidence = np.ones_like(relative)
    confidence[outliers] = 0.4
    result = servo_geometry.align_relative_depth_to_sfm(
        relative,
        sfm_depth,
        confidence,
        representation="inverse-depth",
        min_samples=20,
    )
    return result


def semantic_fixture(
    *,
    damage_second: bool = False,
) -> servo_geometry.SemanticConsistencyResult:
    labels = servo_geometry.SemanticLabel
    first = np.full((24, 32), int(labels.SKY), dtype=np.int16)
    first[9:, :] = int(labels.ROAD)
    first[9, :] = int(labels.CURB)
    first[17:19, 14:18] = int(labels.ROAD_MARKING)
    second = first.copy()
    if damage_second:
        second[9:, :20] = int(labels.BUILDING)
    valid = np.ones_like(first, dtype=bool)
    confidence = np.full(first.shape, 0.95, dtype=np.float64)
    frames = [
        servo_geometry.TemporalSemanticFrame(
            "f000",
            first,
            valid,
            confidence,
            "sfm-depth-reprojection-v1",
        ),
        servo_geometry.TemporalSemanticFrame(
            "f001",
            second,
            valid,
            confidence,
            "sfm-depth-reprojection-v1",
        ),
    ]
    return servo_geometry.validate_temporal_semantic_consistency(frames)


def road_fixture() -> tuple[np.ndarray, servo_geometry.RoadSurfaceFit]:
    rng = np.random.default_rng(431)
    forward = np.repeat(np.linspace(0.0, 100.0, 101), 7)
    lateral = np.tile(np.linspace(-4.5, 4.5, 7), 101)
    elevation = 0.02 * forward + 0.012 * np.maximum(forward - 50.0, 0.0)
    bank = 0.025 + 0.00015 * forward
    height = elevation + bank * lateral + rng.normal(0.0, 0.004, len(forward))
    points = np.column_stack((forward, lateral, height))
    floating = rng.choice(len(points), size=70, replace=False)
    points[floating, 2] += rng.uniform(1.5, 3.5, len(floating))
    confidence = np.ones(len(points), dtype=np.float64)
    fit = servo_geometry.fit_piecewise_road_surface(
        points,
        confidence,
        knot_spacing=10.0,
        min_points=100,
        min_support_per_knot=10,
        smoothness=0.05,
    )
    return floating, fit


class ServoGeometryTests(unittest.TestCase):
    def test_depth_storage_marks_unrepresentable_values_unknown(self) -> None:
        values = np.asarray(
            [0.0, 1.5, 65504.0, 70000.0, -2.0, np.nan, np.inf],
            dtype=np.float64,
        )
        encoded, outside = servo_priors.float16_depth_storage(
            values,
            invalid_value=float("nan"),
        )
        self.assertEqual(encoded.dtype, np.float16)
        np.testing.assert_array_equal(
            np.isfinite(encoded),
            np.asarray([True, True, True, False, False, False, False]),
        )
        self.assertEqual(outside, 2)

    def test_temporal_affine_correction_is_smooth_bounded_and_half_strength(self) -> None:
        frames = 41
        base_scale = 2.0
        base_shift = -0.4
        trend = np.linspace(-0.6, 0.6, frames)
        local_scales = base_scale + trend
        local_shifts = base_shift + 0.5 * trend
        local_scales[20] = 20.0
        local_shifts[20] = -30.0

        scales, shifts, document = servo_priors.smooth_temporal_affine_parameters(
            base_scale,
            base_shift,
            local_scales,
            local_shifts,
        )

        self.assertTrue(np.isfinite(scales).all())
        self.assertTrue(np.isfinite(shifts).all())
        self.assertTrue((scales > 0.0).all())
        self.assertLess(float(np.max(np.abs(np.diff(scales, 2)))), 0.08)
        self.assertLess(float(np.max(np.abs(np.diff(shifts, 2)))), 0.08)
        self.assertAlmostEqual(float(scales[0]), 1.70, delta=0.08)
        self.assertAlmostEqual(float(scales[-1]), 2.30, delta=0.08)
        self.assertLess(float(scales[20]), 2.2)
        self.assertEqual(document["blendWithLocal"], 0.5)
        self.assertEqual(
            document["method"],
            "per-frame-robust-affine-median-savgol-half-blend-v1",
        )

    def test_path_coordinates_find_far_evidence_and_bound_endpoint_extension(self) -> None:
        centers = np.column_stack(
            (
                np.arange(151, dtype=np.float64),
                np.zeros(151, dtype=np.float64),
                np.zeros(151, dtype=np.float64),
            )
        )
        path_frame = {
            "centers": centers.tolist(),
            "arcLengths": np.arange(151, dtype=np.float64).tolist(),
            "up": [0.0, 0.0, 1.0],
            "origin": [0.0, 0.0, 0.0],
            "referenceForward": [1.0, 0.0, 0.0],
            "referenceRight": [0.0, 1.0, 0.0],
            "segmentCandidateCount": 16,
            "localTieBreakRadius": 8,
            "endpointTangentExtension": 3.0,
        }
        points = np.asarray(
            [
                [140.25, 2.0, 0.5],
                [152.0, -1.0, 0.25],
                [160.0, 0.0, 0.0],
            ],
            dtype=np.float64,
        )

        local, segments, association_distance = servo_priors.path_coordinates(
            points,
            path_frame,
            hint_index=10,
        )

        # A camera-local search window would incorrectly pull the first point
        # back near station 18/74.  The spatial candidate search must retain
        # the actually observed far-ahead station.
        self.assertEqual(int(segments[0]), 140)
        self.assertAlmostEqual(float(local[0, 0]), 140.25, places=8)
        self.assertAlmostEqual(float(local[0, 1]), 2.0, places=8)
        self.assertAlmostEqual(float(association_distance[0]), 2.0, places=8)

        # Evidence may extend beyond the final camera, but only inside the
        # explicit tangent-support budget.  Farther points retain a large
        # association residual so the surface builder can reject them.
        self.assertEqual(int(segments[1]), 149)
        self.assertAlmostEqual(float(local[1, 0]), 152.0, places=8)
        self.assertAlmostEqual(float(association_distance[1]), 1.0, places=8)
        self.assertAlmostEqual(float(local[2, 0]), 153.0, places=8)
        self.assertAlmostEqual(float(association_distance[2]), 7.0, places=8)

    def test_path_coordinates_keep_crossing_and_overpass_topology(self) -> None:
        centers = np.asarray(
            [
                [-1.0, 0.0, 1.0],
                [1.0, 0.0, 1.0],
                [2.0, 2.0, 1.0],
                [-2.0, 2.0, 0.0],
                [0.0, -1.0, 0.0],
                [0.0, 1.0, 0.0],
            ],
            dtype=np.float64,
        )
        horizontal_steps = np.diff(centers[:, :2], axis=0)
        lengths = np.linalg.norm(horizontal_steps, axis=1)
        arc = np.concatenate(([0.0], np.cumsum(lengths)))
        path_frame = {
            "centers": centers.tolist(),
            "arcLengths": arc.tolist(),
            "up": [0.0, 0.0, 1.0],
            "origin": [0.0, 0.0, 0.0],
            "referenceForward": [1.0, 0.0, 0.0],
            "referenceRight": [0.0, 1.0, 0.0],
            "segmentCandidateCount": 16,
            "localTieBreakRadius": 8,
            "associationTieDistanceFraction": 0.25,
            "associationVerticalWeight": 1.0,
            "endpointTangentExtension": 0.0,
        }

        upper = np.asarray([[1.0e-4, 2.0e-4, 1.0]], dtype=np.float64)
        _, upper_segments, _ = servo_priors.path_coordinates(
            upper, path_frame, hint_index=0
        )
        self.assertEqual(int(upper_segments[0]), 0)

        lower = np.asarray([[1.0e-4, 2.0e-4, 0.0]], dtype=np.float64)
        _, lower_segments, _ = servo_priors.path_coordinates(
            lower, path_frame, hint_index=4
        )
        self.assertEqual(int(lower_segments[0]), 4)

        # Even with no height separation, sub-step spatial jitter at a true
        # crossing is resolved by ordered capture topology rather than the
        # globally closest segment by a fraction of a pixel.
        same_height_frame = dict(path_frame)
        same_height = centers.copy()
        same_height[:, 2] = 0.0
        same_height_frame["centers"] = same_height.tolist()
        _, tied_segments, _ = servo_priors.path_coordinates(
            lower, same_height_frame, hint_index=0
        )
        self.assertEqual(int(tied_segments[0]), 0)

    def test_robust_inverse_depth_alignment_rejects_sparse_outliers(self) -> None:
        result = depth_fixture()
        self.assertAlmostEqual(result.scale, 2.75, places=7)
        self.assertAlmostEqual(result.shift, 0.15, places=7)
        self.assertEqual(result.sample_count, 120)
        self.assertEqual(result.inlier_count, 114)
        self.assertGreater(result.inlier_ratio, 0.94)
        self.assertLess(result.normalized_p95_residual, 1.0e-8)
        aligned = result.apply(np.array([0.1, 0.4]))
        expected = 1.0 / (2.75 * np.array([0.1, 0.4]) + 0.15)
        np.testing.assert_allclose(aligned, expected, rtol=1.0e-8, atol=1.0e-8)

    def test_depth_alignment_supports_direct_depth_and_masks_invalid_samples(self) -> None:
        prediction = np.linspace(1.0, 4.0, 20)
        sparse = 1.8 * prediction + 0.3
        sparse[0] = np.nan
        confidence = np.ones(20)
        confidence[1] = 0.0
        result = servo_geometry.align_relative_depth_to_sfm(
            prediction,
            sparse,
            confidence,
            representation="depth",
            min_samples=10,
        )
        self.assertAlmostEqual(result.scale, 1.8, places=8)
        self.assertAlmostEqual(result.shift, 0.3, places=8)
        self.assertFalse(result.sample_mask[0])
        self.assertFalse(result.sample_mask[1])
        np.testing.assert_allclose(result.apply(prediction[2:]), sparse[2:])

    def test_depth_alignment_rejects_degenerate_or_reversed_evidence(self) -> None:
        with self.assertRaises(servo_geometry.GeometryInputError):
            servo_geometry.align_relative_depth_to_sfm(
                np.ones(20), np.linspace(1.0, 2.0, 20), representation="depth"
            )
        with self.assertRaisesRegex(
            servo_geometry.GeometryInputError, "positively monotonic"
        ):
            servo_geometry.align_relative_depth_to_sfm(
                np.linspace(1.0, 2.0, 20),
                np.linspace(4.0, 2.0, 20),
                representation="depth",
            )

    def test_semantic_schema_excludes_sky_dynamic_and_unknown_geometry(self) -> None:
        labels = servo_geometry.SemanticLabel
        mask = np.array(
            [
                [labels.ROAD, labels.CURB, labels.SKY],
                [labels.VEHICLE, labels.UNKNOWN, labels.TRAFFIC_SIGN_FRONT],
            ],
            dtype=np.int16,
        )
        finite = servo_geometry.finite_static_geometry_mask(mask)
        np.testing.assert_array_equal(
            finite,
            np.array([[True, True, False], [False, False, True]]),
        )
        with self.assertRaisesRegex(servo_geometry.GeometryInputError, "unknown label"):
            servo_geometry.validate_semantic_mask(np.array([[999]], dtype=np.int32))

    def test_temporally_warped_semantics_pass_when_stable_and_fail_when_damaged(self) -> None:
        stable = semantic_fixture()
        self.assertTrue(stable.passes)
        self.assertAlmostEqual(stable.weighted_agreement, 1.0)
        self.assertAlmostEqual(stable.group_iou["road"], 1.0)
        damaged = semantic_fixture(damage_second=True)
        self.assertFalse(damaged.passes)
        self.assertIn("road_semantic_iou_below_policy", damaged.failures)

    def test_temporal_semantic_validation_rejects_unwarped_masks(self) -> None:
        mask = np.full((4, 4), int(servo_geometry.SemanticLabel.ROAD), dtype=np.int16)
        frame = servo_geometry.TemporalSemanticFrame(
            "f000", mask, np.ones_like(mask, bool), np.ones_like(mask, float), "raw"
        )
        with self.assertRaisesRegex(servo_geometry.GeometryInputError, "warp provenance"):
            servo_geometry.validate_temporal_semantic_consistency([frame, frame])

    def test_piecewise_road_fit_preserves_grade_bank_and_rejects_floaters(self) -> None:
        floating, fit = road_fixture()
        self.assertGreater(fit.inlier_ratio, 0.88)
        self.assertLess(fit.p95_absolute_residual, 0.012)
        self.assertGreater(fit.covered_knot_fraction, 0.95)
        self.assertTrue(np.all(fit.grades[:4] > 0.015))
        self.assertTrue(np.all(fit.grades[-4:] > 0.025))
        self.assertGreater(float(np.median(fit.banks)), 0.02)
        self.assertLess(float(np.median(fit.banks)), 0.05)
        self.assertLess(int(np.count_nonzero(fit.inlier_mask[floating])), 5)

        query = np.array([[25.0, -3.0, 0.0], [75.0, 3.0, 0.0]])
        truth = np.array(
            [
                0.02 * 25.0 + (0.025 + 0.00015 * 25.0) * -3.0,
                0.02 * 75.0
                + 0.012 * 25.0
                + (0.025 + 0.00015 * 75.0) * 3.0,
            ]
        )
        np.testing.assert_allclose(fit.predict(query), truth, atol=0.025)
        outside = fit.predict(np.array([[-1.0, 0.0, 0.0], [101.0, 0.0, 0.0]]))
        self.assertTrue(np.isnan(outside).all())
        self.assertTrue(np.isnan(fit.predict(np.array([[50.0, 20.0, 0.0]]))).all())
        self.assertTrue(
            np.isfinite(
                fit.predict(
                    np.array([[-1.0, 0.0, 0.0]]), allow_extrapolation=True
                )
            ).all()
        )

    def test_observed_surface_keeps_t_branch_without_filling_orphans(self) -> None:
        rng = np.random.default_rng(773)
        main_forward = np.repeat(np.arange(0.0, 20.01, 0.5), 9)
        main_lateral = np.tile(np.arange(-2.0, 2.01, 0.5), 41)
        main_height = 0.012 * main_forward + 0.018 * main_lateral
        main = np.column_stack((main_forward, main_lateral, main_height))
        primary = servo_geometry.fit_piecewise_road_surface(
            main,
            np.ones(len(main), dtype=np.float64),
            knot_spacing=2.0,
            min_points=100,
            min_support_per_knot=8,
            smoothness=0.03,
        )

        branch_forward = np.repeat(np.arange(9.5, 10.51, 0.5), 17)
        branch_lateral = np.tile(np.arange(2.0, 10.01, 0.5), 3)
        branch_height = 0.012 * branch_forward + 0.018 * branch_lateral
        branch = np.column_stack(
            (branch_forward, branch_lateral, branch_height)
        )
        orphan_forward = np.repeat(np.arange(17.0, 18.01, 0.5), 3)
        orphan_lateral = np.tile(np.arange(8.0, 9.01, 0.5), 3)
        orphan_height = 0.012 * orphan_forward + 0.018 * orphan_lateral
        orphan = np.column_stack(
            (orphan_forward, orphan_lateral, orphan_height)
        )
        nonroad_forward = np.repeat(np.arange(4.0, 5.01, 0.5), 3)
        nonroad_lateral = np.tile(np.arange(7.0, 8.01, 0.5), 3)
        nonroad_height = 0.012 * nonroad_forward + 0.018 * nonroad_lateral
        nonroad = np.column_stack(
            (nonroad_forward, nonroad_lateral, nonroad_height)
        )

        observed: list[np.ndarray] = []
        confidence: list[np.ndarray] = []
        frame_ids: list[np.ndarray] = []
        road = np.vstack((main, branch, orphan))
        for frame in range(4):
            noisy = road.copy()
            noisy[:, 2] += rng.normal(0.0, 0.0015, len(noisy))
            observed.append(noisy)
            confidence.append(np.full(len(noisy), 0.95, dtype=np.float64))
            frame_ids.append(np.full(len(noisy), frame, dtype=np.int64))
        # A repeated zero-confidence region represents samples rejected by the
        # semantic road mask.  It must not create support even though it lies
        # inside the broad horizontal bounds of the observations.
        observed.append(nonroad)
        confidence.append(np.zeros(len(nonroad), dtype=np.float64))
        frame_ids.append(np.full(len(nonroad), 10, dtype=np.int64))
        # Sparse floating depths inside otherwise valid cells exercise robust
        # per-cell rejection without deleting the branch.
        floaters = branch[::7].copy()
        floaters[:, 2] += 1.5
        observed.append(floaters)
        confidence.append(np.full(len(floaters), 0.8, dtype=np.float64))
        frame_ids.append(np.full(len(floaters), 20, dtype=np.int64))

        local = servo_geometry.fit_observed_road_surface(
            np.concatenate(observed),
            np.concatenate(confidence),
            np.concatenate(frame_ids),
            primary_surface=primary,
            cell_size=0.5,
            min_samples_per_cell=3,
            min_frames_per_cell=3,
            smoothness=0.05,
        )
        surface = servo_geometry.EvidenceBoundedRoadSurfaceFit(primary, local)

        branch_query = branch[branch[:, 1] >= 3.0]
        prediction = surface.predict(branch_query)
        self.assertTrue(np.isfinite(prediction).all())
        self.assertLess(
            float(np.percentile(np.abs(prediction - branch_query[:, 2]), 95)),
            0.02,
        )
        self.assertTrue(
            np.isfinite(surface.predict(np.asarray([[5.0, 0.0, 0.0]]))).all()
        )
        self.assertTrue(
            np.isnan(surface.predict(np.asarray([[17.5, 8.5, 0.0]]))).all()
        )
        self.assertTrue(
            np.isnan(surface.predict(np.asarray([[4.5, 7.5, 0.0]]))).all()
        )
        self.assertTrue(
            np.isnan(surface.predict(np.asarray([[5.0, 5.0, 0.0]]))).all()
        )
        self.assertTrue(
            np.isnan(surface.predict(np.asarray([[50.0, 50.0, 0.0]]))).all()
        )
        self.assertGreaterEqual(local.component_count, 2)
        self.assertLess(local.retained_cell_count, local.candidate_cell_count)
        self.assertLess(local.p95_absolute_residual, 0.02)

        # A local correction must win wherever repeated observed evidence and
        # the broad primary corridor overlap. Otherwise intersections cannot
        # correct a path-wide surface even after the graph is fitted.
        deliberately_offset_local = dataclasses.replace(
            local, heights=local.heights + 0.25
        )
        corrected_surface = servo_geometry.EvidenceBoundedRoadSurfaceFit(
            primary, deliberately_offset_local
        )
        overlap_query = np.asarray([[5.0, 0.0, 0.0]])
        self.assertAlmostEqual(
            float(corrected_surface.predict(overlap_query)[0]),
            float(deliberately_offset_local.predict(overlap_query)[0]),
            places=10,
        )

    def test_arbitrary_sfm_scale_cannot_enter_collision_validation(self) -> None:
        _, road = road_fixture()
        gate = servo_geometry.evaluate_geometry_safety_gate(
            depth_fixture(),
            road,
            semantic_fixture(),
            geometry_provenance(servo_geometry.ScaleProvenance.SFM_ARBITRARY),
            servo_geometry.GeometryObservationMetrics(0.0, 0.0, 0.0),
        )
        self.assertFalse(gate.eligible_for_collision_validation)
        self.assertIn("metric_scale_anchor_missing", gate.failures)
        self.assertIn("metric_road_residual_tolerance_not_configured", gate.failures)

    def test_repeated_stacked_road_layers_block_primary_fallback(self) -> None:
        forward = np.repeat(np.arange(0.0, 10.01, 0.5), 5)
        lateral = np.tile(np.arange(-1.0, 1.01, 0.5), 21)
        ground = np.column_stack((forward, lateral, np.zeros_like(forward)))
        primary = servo_geometry.fit_piecewise_road_surface(
            ground,
            np.ones(len(ground), dtype=np.float64),
            knot_spacing=1.0,
            min_points=50,
            min_support_per_knot=3,
            smoothness=0.02,
        )
        stacked = ground[
            (ground[:, 0] >= 4.0)
            & (ground[:, 0] <= 6.0)
            & (np.abs(ground[:, 1]) <= 0.5)
        ].copy()
        stacked[:, 2] = 1.0
        points: list[np.ndarray] = []
        frames: list[np.ndarray] = []
        for frame in range(4):
            points.append(ground)
            frames.append(np.full(len(ground), frame, dtype=np.int64))
        for frame in (10, 12, 14):
            points.append(stacked)
            frames.append(np.full(len(stacked), frame, dtype=np.int64))
        values = np.concatenate(points)
        frame_ids = np.concatenate(frames)
        observed = servo_geometry.fit_observed_road_surface(
            values,
            np.ones(len(values), dtype=np.float64),
            frame_ids,
            primary_surface=primary,
            cell_size=0.5,
            min_samples_per_cell=3,
            min_frames_per_cell=2,
            smoothness=0.03,
        )
        surface = servo_geometry.EvidenceBoundedRoadSurfaceFit(primary, observed)
        self.assertGreater(observed.ambiguous_cell_count, 0)
        self.assertGreater(len(observed.blocked_cell_keys), 0)
        self.assertTrue(np.isnan(surface.predict(np.asarray([[5.0, 0.0, 0.0]]))).all())
        self.assertTrue(np.isnan(surface.predict(np.asarray([[5.0, 0.0, 1.0]]))).all())
        self.assertTrue(np.isfinite(surface.predict(np.asarray([[2.0, 0.0, 0.0]]))).all())

    def test_observed_surface_cycle_midpoint_breaks_adaptive_mad_two_cycle(self) -> None:
        forward = np.repeat(np.linspace(0.0, 4.0, 17), 5)
        lateral = np.tile(np.linspace(-1.0, 1.0, 5), 17)
        primary_points = np.column_stack(
            (forward, lateral, np.zeros_like(forward))
        )
        primary = servo_geometry.fit_piecewise_road_surface(
            primary_points,
            np.ones(len(primary_points), dtype=np.float64),
            knot_spacing=1.0,
            min_points=30,
            min_support_per_knot=3,
            smoothness=0.02,
        )

        # This four-cell chain is a minimized reproduction of the production
        # failure.  Re-estimating weighted MAD after every Huber solve toggles
        # between two scales (and two solutions) indefinitely.  Detecting that
        # strict orbit and freezing its midpoint preserves the adaptive branch,
        # then gives one convex Huber objective and a stable fixed point.
        raw_height = 1.0e-3 * np.asarray(
            [
                -1.9983749275449774,
                -0.012484904434624362,
                0.48319613230557407,
                -0.4611579633061765,
            ],
            dtype=np.float64,
        )
        relative_weight = np.asarray(
            [
                1.1731335792796986,
                1.0681903401952506,
                0.9318096598047495,
                0.3041243670777406,
            ],
            dtype=np.float64,
        )
        confidence_per_cell = relative_weight / np.max(relative_weight)
        points: list[list[float]] = []
        confidence: list[float] = []
        frame_ids: list[int] = []
        for cell, height in enumerate(raw_height):
            for frame in range(3):
                points.append([cell + 0.25, 0.25, float(height)])
                confidence.append(float(confidence_per_cell[cell]))
                frame_ids.append(frame)

        observed = servo_geometry.fit_observed_road_surface(
            np.asarray(points, dtype=np.float64),
            np.asarray(confidence, dtype=np.float64),
            np.asarray(frame_ids, dtype=np.int64),
            primary_surface=primary,
            cell_size=1.0,
            min_samples_per_cell=3,
            min_frames_per_cell=3,
            smoothness=0.19510211228426103,
            max_iterations=40,
        )

        self.assertTrue(observed.converged)
        self.assertLess(observed.iterations, 40)
        self.assertEqual(
            observed.termination_reason,
            "cycle-midpoint-fixed-scale-huber",
        )
        self.assertTrue(observed.huber_scale_frozen)
        self.assertGreater(observed.huber_scale, 0.0)
        self.assertTrue(np.isfinite(observed.huber_objective))
        self.assertLessEqual(observed.relative_solution_change, 1.0e-8)
        self.assertLessEqual(observed.normalized_weight_change, 1.0e-5)
        self.assertLess(observed.two_cycle_solution_change, 1.0e-5)
        self.assertLess(observed.two_cycle_weight_change, 1.0e-3)
        self.assertLess(observed.first_order_optimality, 1.0e-5)

    def test_metric_evidence_can_only_become_eligible_under_explicit_policy(self) -> None:
        _, road = road_fixture()
        policy = servo_geometry.GeometrySafetyPolicy(
            min_depth_samples=100,
            min_depth_inlier_ratio=0.90,
            max_depth_normalized_p95=0.01,
            min_road_points=500,
            min_road_inlier_ratio=0.85,
            min_road_covered_knot_fraction=0.90,
            max_road_p95_residual=0.02,
            max_unobserved_fraction=0.01,
            max_finite_sky_geometry_fraction=0.0,
            max_dynamic_geometry_fraction=0.0,
        )
        gate = servo_geometry.evaluate_geometry_safety_gate(
            depth_fixture(),
            road,
            semantic_fixture(),
            geometry_provenance(servo_geometry.ScaleProvenance.KNOWN_DISTANCE),
            servo_geometry.GeometryObservationMetrics(0.0, 0.0, 0.0),
            policy,
        )
        self.assertTrue(gate.eligible_for_collision_validation)
        self.assertTrue(gate.visualization_publishable)
        self.assertEqual(gate.failures, ())

    def test_generated_evidence_is_fail_closed(self) -> None:
        _, road = road_fixture()
        provenance = geometry_provenance(
            servo_geometry.ScaleProvenance.KNOWN_DISTANCE,
            generated_depth=True,
        )
        policy = servo_geometry.GeometrySafetyPolicy(
            min_depth_samples=100,
            min_road_points=500,
            min_road_inlier_ratio=0.85,
            max_road_p95_residual=0.02,
            max_unobserved_fraction=0.01,
            max_dynamic_geometry_fraction=0.0,
        )
        gate = servo_geometry.evaluate_geometry_safety_gate(
            depth_fixture(),
            road,
            semantic_fixture(),
            provenance,
            servo_geometry.GeometryObservationMetrics(0.0, 0.0, 0.0),
            policy,
        )
        self.assertFalse(gate.eligible_for_collision_validation)
        self.assertIn("generated_geometry_not_allowed", gate.failures)

    def test_unverified_gravity_alignment_is_fail_closed(self) -> None:
        _, road = road_fixture()
        policy = servo_geometry.GeometrySafetyPolicy(
            min_depth_samples=100,
            min_road_points=500,
            min_road_inlier_ratio=0.85,
            max_road_p95_residual=0.02,
            max_unobserved_fraction=0.01,
            max_dynamic_geometry_fraction=0.0,
        )
        gate = servo_geometry.evaluate_geometry_safety_gate(
            depth_fixture(),
            road,
            semantic_fixture(),
            geometry_provenance(
                servo_geometry.ScaleProvenance.KNOWN_DISTANCE,
                gravity_aligned=False,
            ),
            servo_geometry.GeometryObservationMetrics(0.0, 0.0, 0.0),
            policy,
        )
        self.assertFalse(gate.eligible_for_collision_validation)
        self.assertIn("gravity_alignment_missing", gate.failures)

    def test_safety_policy_rejects_invalid_tolerances(self) -> None:
        with self.assertRaises(servo_geometry.GeometryInputError):
            servo_geometry.GeometrySafetyPolicy(min_road_inlier_ratio=1.1)
        with self.assertRaises(servo_geometry.GeometryInputError):
            servo_geometry.GeometrySafetyPolicy(max_road_p95_residual=0.0)


def geometry_provenance(
    scale: servo_geometry.ScaleProvenance,
    *,
    generated_depth: bool = False,
    gravity_aligned: bool = True,
) -> servo_geometry.GeometryProvenance:
    evidence = servo_geometry.EvidenceSource
    kinds = servo_geometry.EvidenceKind
    sfm = evidence(
        kinds.SFM_TRIANGULATED,
        "COLMAP",
        "4.1.1",
        "BSD-3-Clause",
        ("capture-001",),
    )
    depth = evidence(
        kinds.GENERATED if generated_depth else kinds.MODEL_INFERRED,
        "depth-fixture",
        "1.0",
        "Apache-2.0",
        ("capture-001",),
        generated=generated_depth,
    )
    semantics = evidence(
        kinds.MODEL_INFERRED,
        "semantic-fixture",
        "1.0",
        "Apache-2.0",
        ("capture-001",),
    )
    return servo_geometry.GeometryProvenance(
        sfm,
        depth,
        semantics,
        scale,
        "servo-world-z-up",
        "surveyed 10 m baseline" if scale.is_metric else None,
        gravity_aligned,
        (
            "bundle-adjusted camera up vectors plus surveyed gravity check"
            if gravity_aligned
            else None
        ),
    )


if __name__ == "__main__":
    unittest.main()
