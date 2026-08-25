from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
    def test_front_to_back_intersection_weights_reset_for_each_pixel(self) -> None:
        alphas = torch.tensor([0.5, 0.5, 0.25, 0.8], dtype=torch.float32)
        rays = torch.tensor([3, 3, 3, 7], dtype=torch.int64)

        weights = servo_train.front_to_back_intersection_weights(alphas, rays)

        torch.testing.assert_close(
            weights,
            torch.tensor([0.5, 0.25, 0.0625, 0.8], dtype=torch.float32),
        )

    def test_contributor_cleanup_changes_only_prequalified_opacity(self) -> None:
        logits = torch.tensor([-1.0, 0.0, 1.0], requires_grad=True)
        qualified = torch.tensor([False, True, False])

        loss = servo_train.contributor_sky_cleanup_loss(logits, qualified)
        loss.backward()

        self.assertEqual(float(logits.grad[0]), 0.0)
        self.assertGreater(float(logits.grad[1]), 0.0)
        self.assertEqual(float(logits.grad[2]), 0.0)

    def test_contributor_cleanup_is_sealed_to_diagnostics(self) -> None:
        diagnostic = {
            "diagnosticProvenance": {
                "schema": servo_train.DIAGNOSTIC_PROVENANCE_SCHEMA,
                "nonPublishable": True,
            }
        }
        settings = {
            "enabled": True,
            "method": servo_train.CONTRIBUTOR_SKY_CLEANUP_METHOD,
            "start_step": 4_500,
            "refine_stop_iter": 4_500,
            "minimum_weight": servo_train.CONTRIBUTOR_SKY_CLEANUP_MINIMUM_WEIGHT,
            "minimum_views": servo_train.CONTRIBUTOR_SKY_CLEANUP_MINIMUM_VIEWS,
            "minimum_view_gap": servo_train.CONTRIBUTOR_SKY_CLEANUP_MINIMUM_VIEW_GAP,
            "audit_factor": servo_train.CONTRIBUTOR_SKY_CLEANUP_AUDIT_FACTOR,
            "loss_weight": 0.01,
        }
        self.assertTrue(
            servo_train.supported_contributor_sky_cleanup_contract(
                diagnostic, **settings
            )
        )
        self.assertFalse(
            servo_train.supported_contributor_sky_cleanup_contract({}, **settings)
        )
        settings["start_step"] = 4_499
        self.assertFalse(
            servo_train.supported_contributor_sky_cleanup_contract(
                diagnostic, **settings
            )
        )

    @unittest.skipUnless(torch.cuda.is_available(), "CUDA is required")
    def test_contributor_ledger_returns_and_commits_receipt(self) -> None:
        from tools.reconstruction.servo_gsplat_runtime import (
            prepare_gsplat_runtime,
        )

        prepare_gsplat_runtime()
        import gsplat.cuda._wrapper as wrapper

        class Dataset:
            def __len__(self) -> int:
                return 1

            def load(self, _index):
                pixels = torch.zeros((8, 8, 3), dtype=torch.float32)
                camera = torch.eye(4, dtype=torch.float32)
                calibration = torch.tensor(
                    [[8.0, 0.0, 4.0], [0.0, 8.0, 4.0], [0.0, 0.0, 1.0]]
                )
                return pixels, camera, calibration, None

            def load_certified_sky_evidence(self, _index):
                return torch.ones((8, 8), dtype=torch.int64)

        empty = torch.empty(0, device="cuda:0", dtype=torch.int64)
        information = {
            "means2d": torch.empty((0, 2), device="cuda:0"),
            "conics": torch.empty((0, 3), device="cuda:0"),
            "opacities": torch.empty(0, device="cuda:0"),
            "tile_size": 16,
            "isect_offsets": torch.zeros((1, 1), device="cuda:0", dtype=torch.int32),
            "flatten_ids": torch.empty(0, device="cuda:0", dtype=torch.int32),
            "gaussian_ids": torch.empty(0, device="cuda:0", dtype=torch.int64),
        }
        parameters = {
            "means": torch.zeros((2, 3), device="cuda:0"),
        }
        hashes = {
            "configurationHash": "sha256:" + "1" * 64,
            "trainingInputHash": "sha256:" + "2" * 64,
            "pipelineCodeHash": "sha256:" + "3" * 64,
        }
        descriptor = {"manifestSha256": "sha256:" + "4" * 64}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with (
                mock.patch.object(
                    wrapper,
                    "rasterize_to_indices_in_range",
                    return_value=(empty, empty, empty),
                ),
                mock.patch.object(
                    servo_train,
                    "rasterize",
                    return_value=(None, None, information),
                ),
                mock.patch.object(servo_train, "emit") as emitted,
            ):
                qualified, ledger = servo_train.build_certified_sky_contributor_ledger(
                    parameters,
                    Dataset(),
                    "cuda:0",
                    sh_degree=3,
                    packed=True,
                    rasterization_mode="antialiased",
                    eps2d=0.3,
                    audit_factor=1,
                    minimum_weight=0.01,
                    minimum_views=2,
                    minimum_view_gap=1,
                    cancel_path=output / "cancel.request",
                    descriptor=descriptor,
                    config=hashes,
                    output=output,
                )
            self.assertEqual(qualified.tolist(), [False, False])
            self.assertEqual(ledger["qualifiedGaussians"], 0)
            receipt = output / "certified-sky-contributor-ledger.json"
            self.assertTrue(receipt.is_file())
            self.assertEqual(json.loads(receipt.read_text())["schema"], ledger["schema"])
            emitted.assert_any_call("contributor_attribution_completed", **ledger)

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


class ObservedDetailGradientLossTests(unittest.TestCase):
    def test_exact_observed_edges_are_zero_and_blur_is_penalized(self) -> None:
        reference = torch.zeros((1, 9, 9, 3), dtype=torch.float32)
        reference[:, :, 4:, :] = 1.0
        confidence = torch.ones((1, 9, 9, 1), dtype=torch.float32)
        semantic = torch.full((1, 9, 9, 1), 2, dtype=torch.int64)

        exact = servo_train.observed_detail_gradient_loss(
            reference.clone(), reference, confidence, semantic
        )
        blurred = reference.clone()
        blurred[:, :, 3:6, :] = torch.tensor([0.25, 0.50, 0.75]).view(1, 1, 3, 1)
        degraded = servo_train.observed_detail_gradient_loss(
            blurred, reference, confidence, semantic
        )

        self.assertAlmostEqual(float(exact), 0.0, places=7)
        self.assertGreater(float(degraded), 0.0)

    def test_unobserved_pixels_do_not_create_detail_targets(self) -> None:
        reference = torch.zeros((1, 7, 7, 3), dtype=torch.float32)
        reference[:, :, 3:, :] = 1.0
        rendered = torch.zeros_like(reference, requires_grad=True)
        confidence = torch.zeros((1, 7, 7, 1), dtype=torch.float32)
        semantic = torch.full((1, 7, 7, 1), 12, dtype=torch.int64)

        loss = servo_train.observed_detail_gradient_loss(
            rendered, reference, confidence, semantic
        )
        loss.backward()

        self.assertEqual(float(loss), 0.0)
        torch.testing.assert_close(rendered.grad, torch.zeros_like(rendered))


if __name__ == "__main__":
    unittest.main()
