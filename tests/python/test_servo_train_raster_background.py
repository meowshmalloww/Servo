from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

import torch


REPOSITORY = Path(__file__).resolve().parents[2]
TRAINER_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_train.py"
TRAINER_SPEC = importlib.util.spec_from_file_location("servo_train_background", TRAINER_PATH)
assert TRAINER_SPEC is not None and TRAINER_SPEC.loader is not None
servo_train = importlib.util.module_from_spec(TRAINER_SPEC)
sys.modules[TRAINER_SPEC.name] = servo_train
TRAINER_SPEC.loader.exec_module(servo_train)


class RasterBackgroundTests(unittest.TestCase):
    def setUp(self) -> None:
        count = 2
        self.parameters = {
            "means": torch.zeros((count, 3)),
            "quats": torch.tensor([[1.0, 0.0, 0.0, 0.0]]).repeat(count, 1),
            "scales": torch.zeros((count, 3)),
            "opacities": torch.zeros(count),
            "sh0": torch.zeros((count, 1, 3)),
            "shN": torch.zeros((count, 0, 3)),
        }
        self.camera = torch.eye(4).unsqueeze(0)
        self.calibration = torch.eye(3).unsqueeze(0)

    def rasterize_with_stub(
        self,
        rendered: torch.Tensor,
        alpha: torch.Tensor,
        *,
        render_mode: str,
        background: torch.Tensor,
        sh_degree: int | None,
        colors_override: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, dict[str, object]]:
        captured: dict[str, object] = {}

        def fake_rasterization(**arguments: object):
            captured.update(arguments)
            return rendered.clone(), alpha.clone(), {"stub": True}

        gsplat_module = ModuleType("gsplat")
        gsplat_module.__path__ = []  # type: ignore[attr-defined]
        rendering_module = ModuleType("gsplat.rendering")
        rendering_module.rasterization = fake_rasterization  # type: ignore[attr-defined]
        gsplat_module.rendering = rendering_module  # type: ignore[attr-defined]
        with mock.patch.dict(
            sys.modules,
            {"gsplat": gsplat_module, "gsplat.rendering": rendering_module},
        ):
            result, returned_alpha, information = servo_train.rasterize(
                self.parameters,
                self.camera,
                self.calibration,
                rendered.shape[-2],
                rendered.shape[-3],
                sh_degree,
                True,
                False,
                "antialiased",
                0.3,
                render_mode=render_mode,
                colors_override=colors_override,
                backgrounds=background,
            )

        self.assertIsNone(captured["backgrounds"])
        torch.testing.assert_close(returned_alpha, alpha)
        self.assertEqual(information, {"stub": True})
        return result, captured

    def test_rgb_background_is_composited_after_packed_rasterization(self) -> None:
        rendered = torch.tensor([[[[0.10, 0.20, 0.30], [0.40, 0.20, 0.10]]]])
        alpha = torch.tensor([[[[0.25], [1.00]]]])
        background = torch.tensor([[0.20, 0.40, 0.60]])

        result, _ = self.rasterize_with_stub(
            rendered,
            alpha,
            render_mode="RGB",
            background=background,
            sh_degree=0,
        )

        expected = rendered + (1.0 - alpha) * background[:, None, None, :]
        torch.testing.assert_close(result, expected)

    def test_rgb_expected_depth_composites_rgb_but_preserves_depth(self) -> None:
        rendered = torch.tensor([[[[0.10, 0.20, 0.30, 7.50]]]])
        alpha = torch.tensor([[[[0.50]]]])
        background = torch.tensor([[0.20, 0.40, 0.60]])

        result, _ = self.rasterize_with_stub(
            rendered,
            alpha,
            render_mode="RGB+ED",
            background=background,
            sh_degree=0,
        )

        torch.testing.assert_close(
            result[..., :3],
            rendered[..., :3] + (1.0 - alpha) * background[:, None, None, :],
        )
        torch.testing.assert_close(result[..., 3:], rendered[..., 3:])

    def test_directional_image_background_composites_each_pixel_only_in_rgb(self) -> None:
        rendered = torch.tensor(
            [[[[0.10, 0.20, 0.30, 2.0], [0.40, 0.50, 0.60, 3.0]]]]
        )
        alpha = torch.tensor([[[[0.25], [0.75]]]])
        background = torch.tensor(
            [[[[0.90, 0.80, 0.70], [0.20, 0.40, 0.60]]]]
        )

        result, _ = self.rasterize_with_stub(
            rendered,
            alpha,
            render_mode="RGB+ED",
            background=background,
            sh_degree=0,
        )

        torch.testing.assert_close(
            result[..., :3], rendered[..., :3] + (1.0 - alpha) * background
        )
        torch.testing.assert_close(result[..., 3:], rendered[..., 3:])

    def test_one_channel_moment_uses_one_channel_background(self) -> None:
        rendered = torch.tensor([[[[2.00], [3.00]]]])
        alpha = torch.tensor([[[[0.25], [0.75]]]])
        background = torch.tensor([[4.00]])
        colors_override = torch.zeros((2, 1))

        result, captured = self.rasterize_with_stub(
            rendered,
            alpha,
            render_mode="RGB",
            background=background,
            sh_degree=None,
            colors_override=colors_override,
        )

        expected = rendered + (1.0 - alpha) * background[:, None, None, :]
        torch.testing.assert_close(result, expected)
        self.assertEqual(tuple(captured["colors"].shape), (2, 1))  # type: ignore[union-attr]

    def test_depth_only_output_is_not_background_composited(self) -> None:
        rendered = torch.tensor([[[[8.25]]]])
        alpha = torch.tensor([[[[0.10]]]])
        background = torch.tensor([[0.20, 0.40, 0.60]])

        result, _ = self.rasterize_with_stub(
            rendered,
            alpha,
            render_mode="ED",
            background=background,
            sh_degree=0,
        )

        torch.testing.assert_close(result, rendered)


if __name__ == "__main__":
    unittest.main()
