from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np


REPOSITORY = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_road_semantics.py"
SPEC = importlib.util.spec_from_file_location("servo_road_semantics", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
servo_road_semantics = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = servo_road_semantics
SPEC.loader.exec_module(servo_road_semantics)


WIDTH = 320
HEIGHT = 192


def road_scene() -> tuple[np.ndarray, np.ndarray]:
    image = np.full((HEIGHT, WIDTH, 3), (72, 72, 72), dtype=np.uint8)
    road = np.zeros((HEIGHT, WIDTH), dtype=bool)
    road[40:, 18:302] = True
    image[~road] = (35, 50, 35)
    return image, road


def recall(predicted: np.ndarray, expected: np.ndarray) -> float:
    return float(np.count_nonzero(predicted & expected) / max(np.count_nonzero(expected), 1))


def manual_evidence(
    proposal: np.ndarray,
    *,
    support: np.ndarray | None = None,
    confidence: float = 0.9,
    paint_class_id: int = 1,
) -> servo_road_semantics.RoadPaintEvidence:
    proposal = np.asarray(proposal, dtype=bool)
    road_support = np.ones(proposal.shape, dtype=bool) if support is None else support.astype(bool)
    paint_class = np.zeros(proposal.shape, dtype=np.uint8)
    paint_class[proposal] = int(paint_class_id)
    scores = np.zeros(proposal.shape, dtype=np.float32)
    scores[proposal] = confidence
    return servo_road_semantics.RoadPaintEvidence(
        paint_class=paint_class,
        candidate_mask=proposal,
        confidence=scores,
        road_support=road_support,
        provenance={"schema": servo_road_semantics.ROAD_PAINT_SCHEMA},
        metrics={},
    )


def identity_warp(height: int, width: int) -> np.ndarray:
    x, y = np.meshgrid(
        np.arange(width, dtype=np.float32),
        np.arange(height, dtype=np.float32),
    )
    return np.stack((x, y), axis=-1)


class RoadPaintExtractionTests(unittest.TestCase):
    def test_detects_solid_white_and_dashed_yellow_at_target_resolution(self) -> None:
        image, road = road_scene()
        white_expected = np.zeros(road.shape, dtype=np.uint8)
        cv2.line(image, (92, 50), (80, 188), (235, 235, 235), 7)
        cv2.line(white_expected, (92, 50), (80, 188), 1, 7)

        yellow_expected = np.zeros(road.shape, dtype=np.uint8)
        for y0 in range(52, 183, 28):
            cv2.line(image, (214, y0), (218, min(y0 + 15, 188)), (25, 205, 230), 7)
            cv2.line(yellow_expected, (214, y0), (218, min(y0 + 15, 188)), 1, 7)

        result = servo_road_semantics.extract_road_paint_evidence(
            image,
            road,
            target_size=(WIDTH, HEIGHT),
        )

        white = result.paint_class == int(servo_road_semantics.RoadPaintClass.WHITE)
        yellow = result.paint_class == int(servo_road_semantics.RoadPaintClass.YELLOW)
        self.assertGreater(recall(white, white_expected), 0.72)
        self.assertGreater(recall(yellow, yellow_expected), 0.72)
        self.assertEqual(result.metrics["targetWidth"], WIDTH)
        self.assertEqual(result.provenance["pretrainedWeights"], None)
        self.assertEqual(
            result.metrics["confidence"]["meaning"],
            "heuristic-evidence-score-not-probability",
        )

    def test_preserves_arrow_and_crosswalk_components(self) -> None:
        image, road = road_scene()
        expected = np.zeros(road.shape, dtype=np.uint8)
        cv2.arrowedLine(image, (145, 172), (145, 82), (240, 240, 240), 10, tipLength=0.32)
        cv2.arrowedLine(expected, (145, 172), (145, 82), 1, 10, tipLength=0.32)
        for y0 in (62, 77, 92, 107):
            cv2.rectangle(image, (205, y0), (285, y0 + 7), (235, 235, 235), -1)
            cv2.rectangle(expected, (205, y0), (285, y0 + 7), 1, -1)

        result = servo_road_semantics.extract_road_paint_evidence(image, road)

        self.assertGreater(recall(result.candidate_mask, expected), 0.58)
        self.assertGreater(result.metrics["components"]["kept"], 1)

    def test_local_contrast_recovers_paint_across_cast_shadow(self) -> None:
        image, road = road_scene()
        cv2.line(image, (120, 45), (108, 189), (232, 232, 232), 8)
        expected = np.zeros(road.shape, dtype=np.uint8)
        cv2.line(expected, (120, 45), (108, 189), 1, 8)

        shadow = np.zeros_like(road)
        shadow[102:, 18:302] = True
        image[shadow] = np.clip(image[shadow].astype(np.float32) * 0.42, 0, 255).astype(np.uint8)

        result = servo_road_semantics.extract_road_paint_evidence(image, road)
        bright_expected = expected & ~shadow
        shadow_expected = expected & shadow

        self.assertGreater(recall(result.candidate_mask, bright_expected), 0.68)
        self.assertGreater(recall(result.candidate_mask, shadow_expected), 0.58)
        # A broad illumination step must not turn into a paint stripe.
        boundary_band = np.zeros_like(road)
        boundary_band[98:106, 200:280] = True
        self.assertLess(np.count_nonzero(result.candidate_mask & boundary_band), 12)

    def test_bright_nonroad_objects_never_produce_output(self) -> None:
        image, road = road_scene()
        image[4:34, 24:140] = (255, 255, 255)
        image[5:35, 180:292] = (0, 235, 255)
        cv2.line(image, (100, 60), (92, 184), (238, 238, 238), 7)

        result = servo_road_semantics.extract_road_paint_evidence(image, road)

        self.assertFalse(np.any(result.candidate_mask[~result.road_support]))
        self.assertFalse(np.any(result.paint_class[~result.road_support]))
        self.assertTrue(np.all(result.confidence[~result.road_support] == 0.0))
        self.assertGreater(np.count_nonzero(result.candidate_mask), 40)

    def test_resizing_is_deterministic_and_mask_uses_nearest_neighbor(self) -> None:
        image, road = road_scene()
        cv2.line(image, (104, 52), (96, 188), (240, 240, 240), 8)
        first = servo_road_semantics.extract_road_paint_evidence(
            image,
            road,
            target_size=(160, 96),
        )
        second = servo_road_semantics.extract_road_paint_evidence(
            image,
            road,
            target_size=(160, 96),
        )

        np.testing.assert_array_equal(first.paint_class, second.paint_class)
        np.testing.assert_array_equal(first.confidence, second.confidence)
        self.assertEqual(first.paint_class.shape, (96, 160))
        self.assertEqual(first.provenance["resampling"]["semanticRoadMask"], "nearest")

    def test_implausibly_dense_paint_is_suppressed_fail_closed(self) -> None:
        image, road = road_scene()
        # Many individually thin, bright, neutral components can resemble
        # road paint locally while being globally incompatible with a road.
        for x in range(28, 296, 12):
            cv2.line(image, (x, 50), (x, 188), (238, 238, 238), 5)

        result = servo_road_semantics.extract_road_paint_evidence(image, road)

        self.assertTrue(result.metrics["frameSuppressed"])
        self.assertGreater(result.metrics["preSuppressionPaintFractionOfRoad"], 0.08)
        self.assertEqual(result.metrics["candidatePixels"], 0)
        self.assertFalse(np.any(result.candidate_mask))
        self.assertTrue(np.all(result.confidence == 0.0))


class RoadPaintConsensusTests(unittest.TestCase):
    def test_rejects_one_frame_false_positive_and_accepts_repeated_paint(self) -> None:
        shape = (48, 64)
        stable = np.zeros(shape, dtype=bool)
        stable[12:34, 17:21] = True
        transient = np.zeros(shape, dtype=bool)
        transient[22:28, 42:49] = True
        reference_proposal = stable | transient
        shifted_stable = np.zeros(shape, dtype=bool)
        shifted_stable[:, 3:] = stable[:, :-3]
        warp = identity_warp(*shape)
        warp[:, :, 0] += 3.0

        result = servo_road_semantics.calibrated_multiframe_paint_consensus(
            manual_evidence(reference_proposal),
            [manual_evidence(shifted_stable), manual_evidence(shifted_stable)],
            [warp, warp],
        )

        self.assertTrue(np.all(result.accepted_mask[stable]))
        self.assertTrue(np.all(result.rejected_mask[transient]))
        self.assertEqual(result.metrics["acceptedPixels"], int(np.count_nonzero(stable)))
        self.assertEqual(result.metrics["rejectedPixels"], int(np.count_nonzero(transient)))
        self.assertEqual(
            result.provenance["correspondenceConvention"],
            "reference-pixel-to-observation-source-xy",
        )

    def test_unsupported_proposals_remain_unknown(self) -> None:
        shape = (32, 40)
        proposal = np.zeros(shape, dtype=bool)
        proposal[8:20, 12:16] = True
        unsupported = np.zeros(shape, dtype=bool)
        warp = identity_warp(*shape)
        warp[proposal] = np.nan

        result = servo_road_semantics.calibrated_multiframe_paint_consensus(
            manual_evidence(proposal),
            [manual_evidence(unsupported), manual_evidence(unsupported)],
            [warp, warp],
        )

        self.assertFalse(np.any(result.accepted_mask[proposal]))
        self.assertFalse(np.any(result.rejected_mask[proposal]))
        self.assertTrue(
            np.all(
                result.decision[proposal]
                == int(servo_road_semantics.ConsensusDecision.UNKNOWN)
            )
        )
        self.assertEqual(result.metrics["unsupportedPixels"], int(np.count_nonzero(proposal)))

    def test_same_color_gate_does_not_promote_a_yellow_reference_as_white(self) -> None:
        shape = (32, 40)
        proposal = np.zeros(shape, dtype=bool)
        proposal[8:24, 18:22] = True
        yellow = int(servo_road_semantics.RoadPaintClass.YELLOW)
        white = int(servo_road_semantics.RoadPaintClass.WHITE)

        result = servo_road_semantics.calibrated_multiframe_paint_consensus(
            manual_evidence(proposal, paint_class_id=yellow),
            [
                manual_evidence(proposal, paint_class_id=white),
                manual_evidence(proposal, paint_class_id=white),
            ],
            [identity_warp(*shape), identity_warp(*shape)],
            config=servo_road_semantics.TemporalConsensusConfig(
                minimum_observations=3,
                minimum_agreeing_observations=2,
                minimum_agreement_ratio=0.60,
                require_same_color=True,
            ),
        )

        self.assertFalse(np.any(result.accepted_mask[proposal]))
        self.assertTrue(np.all(result.rejected_mask[proposal]))


if __name__ == "__main__":
    unittest.main()
