from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import torch


REPOSITORY = Path(__file__).resolve().parents[2]
TRAINER_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_train.py"
TRAINER_SPEC = importlib.util.spec_from_file_location(
    "servo_train_semantic_sky", TRAINER_PATH
)
assert TRAINER_SPEC is not None and TRAINER_SPEC.loader is not None
servo_train = importlib.util.module_from_spec(TRAINER_SPEC)
sys.modules[TRAINER_SPEC.name] = servo_train
TRAINER_SPEC.loader.exec_module(servo_train)


class SemanticSkyOpacityLossTests(unittest.TestCase):
    def test_gradient_descends_only_observed_sky_alpha(self) -> None:
        alpha = torch.tensor(
            [[[[0.20], [0.90], [0.50]], [[0.10], [0.80], [0.30]]]],
            dtype=torch.float32,
            requires_grad=True,
        )
        semantic = torch.tensor(
            [[[[17], [1], [17]], [[18], [0], [17]]]], dtype=torch.int64
        )

        loss, samples = servo_train.semantic_sky_opacity_loss(alpha, semantic)

        self.assertEqual(samples, 3)
        torch.testing.assert_close(loss, torch.tensor([0.20, 0.50, 0.30]).mean())
        loss.backward()
        expected_gradient = torch.tensor(
            [
                [
                    [[1.0 / 3.0], [0.0], [1.0 / 3.0]],
                    [[0.0], [0.0], [1.0 / 3.0]],
                ]
            ]
        )
        torch.testing.assert_close(alpha.grad, expected_gradient)

        with torch.no_grad():
            updated = alpha - 0.1 * alpha.grad
            updated_loss, updated_samples = servo_train.semantic_sky_opacity_loss(
                updated, semantic
            )
        self.assertEqual(updated_samples, samples)
        self.assertLess(float(updated_loss), float(loss.detach()))

    def test_non_sky_alpha_cannot_change_one_sided_loss(self) -> None:
        semantic = torch.tensor([[[[17], [1], [0], [22]]]], dtype=torch.int64)
        low_non_sky = torch.tensor([[[[0.40], [0.00], [0.00], [0.00]]]])
        high_non_sky = torch.tensor([[[[0.40], [1.00], [0.75], [0.90]]]])

        low_loss, low_samples = servo_train.semantic_sky_opacity_loss(
            low_non_sky, semantic
        )
        high_loss, high_samples = servo_train.semantic_sky_opacity_loss(
            high_non_sky, semantic
        )

        self.assertEqual(low_samples, 1)
        self.assertEqual(high_samples, 1)
        torch.testing.assert_close(low_loss, torch.tensor(0.40))
        torch.testing.assert_close(high_loss, low_loss)

    def test_temporal_evidence_limits_gradients_to_confirmed_sky(self) -> None:
        alpha = torch.tensor(
            [[[[0.20], [0.80], [0.60], [0.90]]]], requires_grad=True
        )
        semantic = torch.tensor([[[[17], [17], [17], [1]]]], dtype=torch.int64)
        evidence = torch.tensor(
            [[[[1], [0], [2], [2]]]], dtype=torch.int64
        )

        loss, samples = servo_train.semantic_sky_opacity_loss(
            alpha, semantic, evidence=evidence
        )

        self.assertEqual(samples, 1)
        torch.testing.assert_close(loss, torch.tensor(0.20))
        loss.backward()
        torch.testing.assert_close(
            alpha.grad,
            torch.tensor([[[[1.0], [0.0], [0.0], [0.0]]]]),
        )

    def test_temporal_evidence_rejects_unknown_labels_or_shape(self) -> None:
        alpha = torch.zeros((1, 2, 2, 1))
        semantic = torch.full((1, 2, 2, 1), 17, dtype=torch.int64)
        for evidence in (
            torch.zeros((1, 2, 2), dtype=torch.int64),
            torch.full((1, 2, 2, 1), 3, dtype=torch.int64),
        ):
            with self.subTest(evidence=tuple(evidence.shape)):
                with self.assertRaises(servo_train.TrainingError):
                    servo_train.semantic_sky_opacity_loss(
                        alpha, semantic, evidence=evidence
                    )

    def test_no_sky_returns_differentiable_zero(self) -> None:
        alpha = torch.tensor(
            [[[[0.15], [0.65]], [[0.35], [0.95]]]], requires_grad=True
        )
        semantic = torch.tensor([[[[1], [0]], [[18], [22]]]], dtype=torch.int64)

        loss, samples = servo_train.semantic_sky_opacity_loss(alpha, semantic)

        self.assertEqual(samples, 0)
        self.assertEqual(float(loss.detach()), 0.0)
        self.assertTrue(loss.requires_grad)
        loss.backward()
        torch.testing.assert_close(alpha.grad, torch.zeros_like(alpha))

    def test_nonfinite_sky_alpha_is_excluded_without_poisoning_loss(self) -> None:
        alpha = torch.tensor(
            [[[[float("nan")], [0.40], [float("inf")]]]], requires_grad=True
        )
        semantic = torch.full((1, 1, 3, 1), 17, dtype=torch.int64)

        loss, samples = servo_train.semantic_sky_opacity_loss(alpha, semantic)

        self.assertEqual(samples, 1)
        torch.testing.assert_close(loss, torch.tensor(0.40))
        loss.backward()
        torch.testing.assert_close(
            alpha.grad, torch.tensor([[[[0.0], [1.0], [0.0]]]])
        )

    def test_near_opaque_sky_retains_a_bounded_corrective_gradient(self) -> None:
        alpha = torch.tensor([[[[0.50], [0.99]]]], requires_grad=True)
        semantic = torch.full((1, 1, 2, 1), 17, dtype=torch.int64)

        loss, samples = servo_train.semantic_sky_opacity_loss(alpha, semantic)

        self.assertEqual(samples, 2)
        loss.backward()
        torch.testing.assert_close(alpha.grad, torch.full_like(alpha, 0.5))

    def test_exactly_opaque_sky_remains_finite_and_bounded(self) -> None:
        alpha = torch.tensor([[[[1.0]]]], requires_grad=True)
        semantic = torch.full((1, 1, 1, 1), 17, dtype=torch.int64)

        loss, samples = servo_train.semantic_sky_opacity_loss(alpha, semantic)

        self.assertEqual(samples, 1)
        self.assertTrue(torch.isfinite(loss))
        loss.backward()
        self.assertTrue(torch.isfinite(alpha.grad).all())
        torch.testing.assert_close(alpha.grad, torch.ones_like(alpha))

    def test_tail_bce_only_strengthens_confirmed_sky_interior(self) -> None:
        semantic = torch.full((1, 7, 7, 1), 17, dtype=torch.int64)
        semantic[0, 1, 1, 0] = 1
        alpha = torch.full((1, 7, 7, 1), 0.05, dtype=torch.float32)
        alpha[0, 4, 4, 0] = 0.99  # interior sky: receives tail gradient.
        alpha[0, 0, 3, 0] = 0.99  # image-boundary sky: excluded from tail.
        alpha[0, 2, 2, 0] = 0.99  # next to non-sky: excluded from tail.
        alpha[0, 5, 5, 0] = 0.05  # interior but below threshold.
        alpha[0, 3, 4, 0] = float("nan")
        alpha.requires_grad_()

        base, samples = servo_train.semantic_sky_opacity_loss(
            alpha,
            semantic,
            tail_weight=0.0,
        )
        strengthened, strengthened_samples = servo_train.semantic_sky_opacity_loss(
            alpha,
            semantic,
            tail_threshold=0.10,
            tail_weight=0.05,
            tail_bce_epsilon=0.01,
            tail_erosion_radius=1,
        )

        self.assertEqual(strengthened_samples, samples)
        self.assertGreater(float(strengthened.detach()), float(base.detach()))
        (strengthened - base).backward()
        self.assertGreater(float(alpha.grad[0, 4, 4, 0]), 0.0)
        self.assertEqual(float(alpha.grad[0, 0, 3, 0]), 0.0)
        self.assertEqual(float(alpha.grad[0, 2, 2, 0]), 0.0)
        self.assertEqual(float(alpha.grad[0, 5, 5, 0]), 0.0)
        self.assertEqual(float(alpha.grad[0, 3, 4, 0]), 0.0)

    def test_tail_bce_is_finite_for_exactly_opaque_interior_sky(self) -> None:
        alpha = torch.full((1, 5, 5, 1), 0.05, dtype=torch.float32)
        alpha[0, 2, 2, 0] = 1.0
        alpha.requires_grad_()
        semantic = torch.full((1, 5, 5, 1), 17, dtype=torch.int64)

        base, _ = servo_train.semantic_sky_opacity_loss(alpha, semantic)
        strengthened, _ = servo_train.semantic_sky_opacity_loss(
            alpha,
            semantic,
            tail_weight=0.05,
            tail_erosion_radius=1,
        )

        self.assertTrue(torch.isfinite(strengthened))
        (strengthened - base).backward()
        self.assertTrue(torch.isfinite(alpha.grad).all())
        self.assertGreater(float(alpha.grad[0, 2, 2, 0]), 0.0)

    def test_sky_tail_interior_mask_and_view_diagnostics_are_explicit(self) -> None:
        semantic = torch.full((1, 7, 7, 1), 17, dtype=torch.int64)
        semantic[0, 1, 1, 0] = 1
        interior = servo_train.semantic_sky_tail_interior_mask(
            semantic,
            erosion_radius=1,
        )
        self.assertFalse(bool(interior[0, 0, 0, 0]))
        self.assertFalse(bool(interior[0, 2, 2, 0]))
        self.assertTrue(bool(interior[0, 4, 4, 0]))

        alpha = torch.tensor(
            [[[[0.10], [0.20], [0.80], [1.00]]]], dtype=torch.float32
        )
        diagnostics = servo_train.semantic_sky_view_diagnostic(
            alpha,
            torch.full_like(alpha, 17, dtype=torch.int64),
            "video-000/00000001.png",
        )
        self.assertIsNotNone(diagnostics)
        assert diagnostics is not None
        self.assertEqual(diagnostics["image"], "video-000/00000001.png")
        self.assertEqual(diagnostics["skyPixels"], 4)
        self.assertAlmostEqual(diagnostics["skyAlphaP95"], 0.97, places=6)
        self.assertAlmostEqual(diagnostics["skyAlphaP99"], 0.994, places=6)
        self.assertAlmostEqual(
            diagnostics["skyAlphaAboveTenPercentFraction"], 0.75, places=6
        )

    def test_zero_tail_control_is_sealed_to_nonpublishable_diagnostics(self) -> None:
        diagnostic = {
            "diagnosticProvenance": {
                "schema": servo_train.DIAGNOSTIC_PROVENANCE_SCHEMA,
                "nonPublishable": True,
            }
        }
        shared = {
            "tail_threshold": servo_train.SEMANTIC_SKY_TAIL_THRESHOLD,
            "tail_bce_epsilon": servo_train.SEMANTIC_SKY_TAIL_BCE_EPSILON,
            "tail_erosion_method": servo_train.SEMANTIC_SKY_TAIL_EROSION_METHOD,
            "tail_erosion_radius": servo_train.SEMANTIC_SKY_TAIL_EROSION_RADIUS,
        }
        self.assertTrue(
            servo_train.supported_semantic_sky_opacity_contract(
                {},
                method=servo_train.SEMANTIC_SKY_OPACITY_METHOD,
                tail_weight=servo_train.SEMANTIC_SKY_TAIL_WEIGHT,
                **shared,
            )
        )
        self.assertTrue(
            servo_train.supported_semantic_sky_opacity_contract(
                diagnostic,
                method=servo_train.SEMANTIC_SKY_DIAGNOSTIC_ABLATION_METHOD,
                tail_weight=0.0,
                **shared,
            )
        )
        self.assertFalse(
            servo_train.supported_semantic_sky_opacity_contract(
                {},
                method=servo_train.SEMANTIC_SKY_DIAGNOSTIC_ABLATION_METHOD,
                tail_weight=0.0,
                **shared,
            )
        )
        self.assertFalse(
            servo_train.supported_semantic_sky_opacity_contract(
                diagnostic,
                method=servo_train.SEMANTIC_SKY_DIAGNOSTIC_ABLATION_METHOD,
                tail_weight=0.01,
                **shared,
            )
        )

    def test_all_nonfinite_sky_alpha_returns_differentiable_zero(self) -> None:
        alpha = torch.tensor(
            [[[[float("nan")], [float("inf")]]]], requires_grad=True
        )
        semantic = torch.full((1, 1, 2, 1), 17, dtype=torch.int64)

        loss, samples = servo_train.semantic_sky_opacity_loss(alpha, semantic)

        self.assertEqual(samples, 0)
        self.assertTrue(torch.isfinite(loss))
        self.assertEqual(float(loss.detach()), 0.0)
        loss.backward()
        torch.testing.assert_close(alpha.grad, torch.zeros_like(alpha))

    def test_rejects_mismatched_or_non_batched_shapes(self) -> None:
        invalid = (
            (
                torch.zeros((2, 3, 1)),
                torch.zeros((2, 3, 1), dtype=torch.int64),
            ),
            (
                torch.zeros((1, 2, 3, 2)),
                torch.zeros((1, 2, 3, 2), dtype=torch.int64),
            ),
            (
                torch.zeros((1, 2, 3, 1)),
                torch.zeros((1, 2, 3), dtype=torch.int64),
            ),
            (
                torch.zeros((1, 2, 3, 1)),
                torch.zeros((2, 2, 3, 1), dtype=torch.int64),
            ),
        )

        for alpha, semantic in invalid:
            with self.subTest(alpha=tuple(alpha.shape), semantic=tuple(semantic.shape)):
                with self.assertRaisesRegex(
                    servo_train.TrainingError,
                    r"matching \[camera,height,width,1\] tensors",
                ):
                    servo_train.semantic_sky_opacity_loss(alpha, semantic)


class SemanticPhotometricConfidenceTests(unittest.TestCase):
    def test_rigid_static_pixels_retain_observed_rgb_when_flow_fails(self) -> None:
        """A flow failure is not evidence that static asphalt ceased to exist."""
        temporal = torch.tensor(
            [[[[0.0], [0.10], [0.40], [0.00], [0.90], [0.70], [0.60], [0.50]]]],
            dtype=torch.float32,
        )
        semantic = torch.tensor(
            [[[[1], [16], [16], [23], [23], [17], [18], [0]]]],
            dtype=torch.int64,
        )

        fused = servo_train.fuse_semantic_photometric_confidence(
            temporal, semantic
        )

        expected = torch.tensor(
            [[[[1.0], [0.10], [0.40], [0.00], [0.90], [0.0], [0.0], [0.0]]]],
            dtype=torch.float32,
        )
        torch.testing.assert_close(fused, expected)

    def test_preserves_nonrigid_flow_gradients_above_the_safety_floor(self) -> None:
        temporal = torch.tensor(
            [[[[0.0], [0.60], [0.30]]]], dtype=torch.float32, requires_grad=True
        )
        semantic = torch.tensor(
            [[[[1], [16], [23]]]], dtype=torch.int64
        )

        fused = servo_train.fuse_semantic_photometric_confidence(
            temporal, semantic
        )
        fused.sum().backward()

        # Road remains a full observed-RGB target independent of ambiguous
        # optical flow; non-rigid classes retain only their measured flow weight.
        torch.testing.assert_close(
            temporal.grad, torch.tensor([[[[0.0], [1.0], [1.0]]]])
        )

    def test_video_capture_exclusion_cannot_be_reenabled_as_road(self) -> None:
        temporal = torch.ones((1, 5, 3, 1), dtype=torch.float32)
        semantic = torch.ones((1, 5, 3, 1), dtype=torch.int64)
        exclusion = servo_train.video_capture_bottom_exclusion_mask(
            "video-000/frame-0001.png", 5, 3, "cpu"
        )

        fused = servo_train.fuse_semantic_photometric_confidence(
            temporal, semantic, hard_exclusion=exclusion
        )

        self.assertIsNotNone(exclusion)
        torch.testing.assert_close(fused[:, :4], torch.ones((1, 4, 3, 1)))
        torch.testing.assert_close(fused[:, 4:], torch.zeros((1, 1, 3, 1)))
        self.assertIsNone(
            servo_train.video_capture_bottom_exclusion_mask(
                "photos/frame-0001.png", 5, 3, "cpu"
            )
        )

    def test_rejects_nonfinite_or_out_of_range_temporal_evidence(self) -> None:
        semantic = torch.ones((1, 1, 2, 1), dtype=torch.int64)
        for temporal in (
            torch.tensor([[[[float("nan")], [0.0]]]]),
            torch.tensor([[[[-0.01], [0.0]]]]),
            torch.tensor([[[[1.01], [0.0]]]]),
        ):
            with self.subTest(temporal=temporal):
                with self.assertRaises(servo_train.TrainingError):
                    servo_train.fuse_semantic_photometric_confidence(
                        temporal, semantic
                    )


if __name__ == "__main__":
    unittest.main()
