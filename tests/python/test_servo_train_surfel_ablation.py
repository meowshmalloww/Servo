from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path

import torch


REPOSITORY = Path(__file__).resolve().parents[2]
TRAINER_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_train.py"
TRAINER_SPEC = importlib.util.spec_from_file_location(
    "servo_train_surfel_ablation", TRAINER_PATH
)
assert TRAINER_SPEC is not None and TRAINER_SPEC.loader is not None
servo_train = importlib.util.module_from_spec(TRAINER_SPEC)
sys.modules[TRAINER_SPEC.name] = servo_train
TRAINER_SPEC.loader.exec_module(servo_train)


def _diagnostic_config() -> dict:
    return {
        "diagnosticProvenance": {
            "schema": servo_train.DIAGNOSTIC_PROVENANCE_SCHEMA,
            "nonPublishable": True,
        }
    }


def _valid_kwargs(**overrides) -> dict:
    values = {
        "schema": servo_train.SURFEL_ABLATION_SCHEMA,
        "method": servo_train.SURFEL_ABLATION_METHOD,
        "depth_distortion_weight": 0.01,
        "normal_consistency_weight": 0.05,
        "normal_consistency_start": 600,
        "coarse_steps": 500,
    }
    values.update(overrides)
    return values


class SurfelAblationContractTests(unittest.TestCase):
    def test_diagnostic_config_with_sealed_values_is_accepted(self) -> None:
        self.assertTrue(
            servo_train.supported_surfel_ablation_contract(
                _diagnostic_config(), **_valid_kwargs()
            )
        )

    def test_publishable_config_is_rejected(self) -> None:
        self.assertFalse(
            servo_train.supported_surfel_ablation_contract({}, **_valid_kwargs())
        )

    def test_wrong_schema_or_method_is_rejected(self) -> None:
        self.assertFalse(
            servo_train.supported_surfel_ablation_contract(
                _diagnostic_config(),
                **_valid_kwargs(schema="some.other.schema/v1"),
            )
        )
        self.assertFalse(
            servo_train.supported_surfel_ablation_contract(
                _diagnostic_config(),
                **_valid_kwargs(method="not-the-pinned-kernel"),
            )
        )

    def test_out_of_bounds_weights_are_rejected(self) -> None:
        self.assertFalse(
            servo_train.supported_surfel_ablation_contract(
                _diagnostic_config(), **_valid_kwargs(depth_distortion_weight=2.0)
            )
        )
        self.assertFalse(
            servo_train.supported_surfel_ablation_contract(
                _diagnostic_config(), **_valid_kwargs(normal_consistency_weight=-0.1)
            )
        )

    def test_normal_start_must_be_after_coarse_phase(self) -> None:
        self.assertFalse(
            servo_train.supported_surfel_ablation_contract(
                _diagnostic_config(), **_valid_kwargs(normal_consistency_start=400)
            )
        )


class SurfelParameterPolicyTests(unittest.TestCase):
    def test_clamp_pins_only_the_surfel_normal_axis_when_requested(self) -> None:
        parameters = {
            "quats": torch.nn.Parameter(torch.tensor([[2.0, 0.0, 0.0, 0.0]])),
            "scales": torch.nn.Parameter(torch.tensor([[-20.0, 0.5, -3.0]])),
            "opacities": torch.nn.Parameter(torch.tensor([[9.0]])),
        }
        servo_train.clamp_parameters(parameters, pin_surfel_z=True)
        self.assertEqual(float(parameters["scales"][0, 0]), -12.0)
        self.assertEqual(float(parameters["scales"][0, 1]), 0.5)
        self.assertAlmostEqual(
            float(parameters["scales"][0, 2]), math.log(1e-6), places=6
        )

    def test_cleanup_ignores_the_pinned_axis_for_needle_detection(self) -> None:
        count = 256
        generator = torch.Generator().manual_seed(7)
        # Half of the splats carry the pinned surfel normal axis; half are
        # compact 3D blobs. Full-axis anisotropy flags only the pinned half,
        # while in-plane anisotropy must flag neither.
        pinned_z = torch.full((count // 2, 1), math.log(1e-6))
        blob_z = torch.full((count - count // 2, 1), math.log(0.05))
        parameters = {
            "means": torch.nn.Parameter(torch.randn(count, 3, generator=generator) * 0.1),
            "sh0": torch.nn.Parameter(torch.randn(count, 1, 3, generator=generator) * 0.1),
            "shN": torch.nn.Parameter(torch.randn(count, 15, 3, generator=generator) * 0.02),
            "opacities": torch.nn.Parameter(torch.full((count,), 4.0)),
            "scales": torch.nn.Parameter(
                torch.cat(
                    [
                        torch.full((count, 2), math.log(0.5)),
                        torch.cat([pinned_z, blob_z], dim=0),
                    ],
                    dim=-1,
                )
            ),
            "quats": torch.nn.Parameter(
                torch.nn.functional.normalize(
                    torch.randn(count, 4, generator=generator), dim=-1
                )
            ),
        }
        normalization = {"cleanupRadiusLimitNormalized": 10.0, "cleanupScaleLimitNormalized": 2.0}

        cleaned_3dgs, metrics_3dgs = servo_train.cleanup_parameters(
            parameters, normalization, surfel=False
        )
        cleaned_surfel, metrics_surfel = servo_train.cleanup_parameters(
            parameters, normalization, surfel=True
        )

        self.assertEqual(metrics_3dgs["needleCandidates"], count // 2)
        self.assertEqual(metrics_surfel["needleCandidates"], 0)
        self.assertEqual(int(len(cleaned_surfel["means"])), count)
        self.assertEqual(int(len(cleaned_3dgs["means"])), count - count // 2)

    def test_scale_regularization_stays_finite_for_planar_splats(self) -> None:
        scales = torch.tensor(
            [[math.log(0.5), math.log(0.25), math.log(1e-6)]]
        )
        in_plane = torch.exp(scales[..., :2])
        anisotropy = (
            in_plane.max(dim=-1).values / in_plane.min(dim=-1).values.clamp_min(1e-6)
        )
        loss = in_plane.mean() + torch.relu(anisotropy - 20.0).mean()
        self.assertTrue(torch.isfinite(loss).all())


@unittest.skipUnless(torch.cuda.is_available(), "requires a CUDA device")
class SurfelRasterizeTests(unittest.TestCase):
    def _parameters(self, device: str) -> dict:
        generator = torch.Generator(device="cpu").manual_seed(11)
        count = 512
        cpu = {
            "means": torch.randn(count, 3, generator=generator) * 0.4,
            "sh0": torch.randn(count, 1, 3, generator=generator) * 0.2,
            "shN": torch.randn(count, 15, 3, generator=generator) * 0.05,
            "opacities": torch.rand(count, generator=generator) * 2.0,
            "scales": torch.cat(
                [
                    torch.log(torch.rand(count, 2, generator=generator) * 0.05 + 0.01),
                    torch.full((count, 1), math.log(1e-6)),
                ],
                dim=-1,
            ),
            "quats": torch.nn.functional.normalize(
                torch.randn(count, 4, generator=generator), dim=-1
            ),
        }
        return {
            name: value.to(device).requires_grad_(name != "quats")
            for name, value in cpu.items()
        }

    def test_rasterize_surfel_returns_consistent_normal_maps_and_pinned_axis(self) -> None:
        device = "cuda:0"
        parameters = self._parameters(device)
        camera_to_world = torch.eye(4, device=device).unsqueeze(0)
        camera_to_world[0, :3, 3] = torch.tensor([0.0, 0.0, 3.0], device=device)
        calibration = (
            torch.tensor(
                [[[120.0, 0.0, 64.0], [0.0, 120.0, 48.0], [0.0, 0.0, 1.0]]],
                device=device,
            )
        )
        stored_z_before = parameters["scales"][..., 2].detach().clone()

        rendered, alpha, information = servo_train.rasterize(
            parameters,
            camera_to_world,
            calibration,
            width=128,
            height=96,
            sh_degree=3,
            packed=True,
            absgrad=False,
            rasterization_mode="classic",
            eps2d=0.3,
            render_mode="RGB+ED",
            surfel_ablation={
                "schema": servo_train.SURFEL_ABLATION_SCHEMA,
                "method": servo_train.SURFEL_ABLATION_METHOD,
                "depthDistortionWeight": 0.01,
                "normalConsistencyWeight": 0.05,
                "normalConsistencyStart": 600,
            },
        )

        self.assertTrue(torch.isfinite(rendered).all())
        self.assertTrue(bool(((alpha >= 0.0) & (alpha <= 1.0)).all()))
        self.assertEqual(rendered.shape[-1], 4)
        normals = information["surfelNormal"]
        depth_normals = information["surfelDepthNormal"]
        distortion = information["surfelDistortion"]
        self.assertEqual(normals.shape[-1], 3)
        self.assertEqual(depth_normals.shape, normals.shape)
        self.assertEqual(distortion.shape[-1], 1)
        self.assertTrue(torch.isfinite(distortion).all())
        torch.testing.assert_close(
            parameters["scales"][..., 2], stored_z_before
        )

        gradient_key = information["gradient_2dgs"]
        self.assertTrue(gradient_key.requires_grad)
        (rendered.square().mean() + distortion.mean()).backward()
        self.assertIsNotNone(information["gradient_2dgs"].grad)
        self.assertIsNotNone(parameters["means"].grad)


if __name__ == "__main__":
    unittest.main()
