from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
RECONSTRUCTION = REPOSITORY / "tools" / "reconstruction"


class ReconstructionReleaseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lock = json.loads(
            (RECONSTRUCTION / "worker-lock.json").read_text(encoding="utf-8")
        )
        cls.setup = (RECONSTRUCTION / "setup_native.ps1").read_text(
            encoding="utf-8"
        )

    def test_r7_worker_app_and_lock_contract_match(self) -> None:
        self.assertEqual(self.lock["workerVersion"], "0.7.0")
        self.assertEqual(self.lock["trainerVersion"], "0.7.0")
        self.assertEqual(
            self.lock["pipelineRevision"],
            "native-colmap-servo-road-geometry-r7",
        )

        worker = (RECONSTRUCTION / "servo_worker.py").read_text(encoding="utf-8")
        controller = (
            REPOSITORY
            / "src"
            / "ui"
            / "reconstruction"
            / "ReconstructionController.cpp"
        ).read_text(encoding="utf-8")
        self.assertRegex(worker, r'WORKER_VERSION\s*=\s*"0\.7\.0"')
        self.assertRegex(
            worker,
            r'PIPELINE_REVISION\s*=\s*"native-colmap-servo-road-geometry-r7"',
        )
        self.assertIn('supportedWorkerVersion = "0.7.0"', controller)

    def test_prior_lock_has_complete_content_contract(self) -> None:
        priors = self.lock["geometryPriors"]
        video_depth = priors["videoDepthAnythingSmall"]
        self.assertEqual(
            video_depth["sourceCommit"],
            "4f5ae23172ba60fd7bc11ef671cca678842c7072",
        )
        self.assertEqual(video_depth["sourceArchiveBytes"], 7_905_704)
        self.assertEqual(
            video_depth["sourceArchiveSha256"],
            "012dc88e5feb7e51f5794f9b8013f4c786aa3d61c60b8e0c3c5a45e1e0feb7c5",
        )
        self.assertEqual(video_depth["checkpointBytes"], 116_440_756)
        self.assertEqual(
            video_depth["checkpointSha256"],
            "13379300b739e659f076a59d52e9801bd8d38c541a7e71f73bbca4dcfb013609",
        )
        self.assertEqual(video_depth["license"], "Apache-2.0")
        self.assertEqual(
            video_depth["pythonSourceManifestSha256"],
            "40d096e92b5000790416ac4cc519af64adc8cb74354490535ce73c56b39dc581",
        )

        oneformer = priors["oneFormerAde20kSwinTiny"]
        self.assertEqual(
            oneformer["revision"],
            "05f2812b1eccf9909b3897777450f8d68148cafc",
        )
        self.assertEqual(oneformer["license"], "MIT")
        expected_files = {
            "config.json": (84_284, "091cbc7c980128ae63b2a15d882923f326f85926ef163adad00c24bd90228896"),
            "preprocessor_config.json": (8_709, "2c3c403d8414263e732996bb2ffeab80dd5ced0068ab11bfe5adf476ef75823c"),
            "pytorch_model.bin": (203_389_501, "909b07dbf4129c2bbb8df4498e35dcd46f305e3ec45329d3ff6d4f0360de27f3"),
            "merges.txt": (524_619, "9fd691f7c8039210e0fced15865466c65820d09b63988b0174bfe25de299051a"),
            "vocab.json": (1_059_962, "e089ad92ba36837a0d31433e555c8f45fe601ab5c221d4f607ded32d9f7a4349"),
            "tokenizer_config.json": (807, "64dd88e64d791e3be4d38be62d7e77e0a24df9e79205ac740af505aa2e94c367"),
            "special_tokens_map.json": (472, "c4864a9376a8401918425bed71fc14fc0e81f9b59ec45c1cf96cccb2df508eac"),
        }
        actual_files = {
            name: (metadata["bytes"], metadata["sha256"])
            for name, metadata in oneformer["files"].items()
        }
        self.assertEqual(actual_files, expected_files)

    def test_setup_verifies_and_atomically_publishes_every_prior(self) -> None:
        priors = self.lock["geometryPriors"]
        expected_hashes = {
            priors["videoDepthAnythingSmall"]["sourceArchiveSha256"],
            priors["videoDepthAnythingSmall"]["entryPointSha256"],
            priors["videoDepthAnythingSmall"]["pythonSourceManifestSha256"],
            priors["videoDepthAnythingSmall"]["checkpointSha256"],
            *(
                metadata["sha256"]
                for metadata in priors["oneFormerAde20kSwinTiny"]["files"].values()
            ),
        }
        for digest in expected_hashes:
            self.assertIn(digest, self.setup)
        self.assertIn("Get-FileHash", self.setup)
        self.assertIn("[System.IO.File]::Replace", self.setup)
        self.assertIn("[System.IO.File]::Move", self.setup)
        self.assertIn("-Offline", self.setup)
        self.assertIn("[switch]$ProvisionPriorsOnly", self.setup)
        self.assertNotRegex(self.setup, re.compile(r"docker", re.IGNORECASE))
        self.assertNotRegex(
            self.setup,
            re.compile(r"winget\s+install\s+.*visual\s*studio", re.IGNORECASE),
        )

    def test_geometry_python_packages_are_exactly_pinned(self) -> None:
        requirements = (RECONSTRUCTION / "requirements-native.txt").read_text(
            encoding="utf-8"
        )
        for requirement in (
            "transformers==5.13.0",
            "easydict==1.9",
            "einops==0.8.2",
            "tqdm==4.67.3",
        ):
            self.assertRegex(
                requirements,
                rf"(?m)^{re.escape(requirement)}$",
            )

    def test_geometry_model_execution_is_offline_and_preprocessor_pinned(self) -> None:
        worker = (RECONSTRUCTION / "servo_worker.py").read_text(encoding="utf-8")
        priors = (RECONSTRUCTION / "servo_priors.py").read_text(encoding="utf-8")
        self.assertIn('set_value("HF_HUB_OFFLINE", "1")', worker)
        self.assertIn('set_value("TRANSFORMERS_OFFLINE", "1")', worker)
        self.assertIn('backend="pil"', priors)
        self.assertIn("output_loading_info=True", priors)
        self.assertIn("expected_unexpected", priors)

    def test_pipeline_snapshot_includes_evidence_contract_code(self) -> None:
        worker = (RECONSTRUCTION / "servo_worker.py").read_text(encoding="utf-8")
        for name in (
            "servo_road_semantics.py",
            "servo_sign_evidence.py",
            "servo_environment.py",
        ):
            self.assertTrue((RECONSTRUCTION / name).is_file())
            self.assertRegex(
                worker,
                rf"(?s)PIPELINE_SOURCE_FILES\s*=\s*\(.*{re.escape(name)}.*\)",
            )

    def test_geometry_receipt_gates_observed_surface_and_occlusion_policy(self) -> None:
        worker = (RECONSTRUCTION / "servo_worker.py").read_text(encoding="utf-8")
        trainer = (RECONSTRUCTION / "servo_train.py").read_text(encoding="utf-8")
        for contract_field in (
            '"anchorCellCount"',
            '"maximumCellP95Residual"',
            '"correspondenceOcclusionPolicy"',
            '"longestConsecutiveSuppressedFrames"',
            '"nearerObservationRelativeTolerance"',
            '"maximumSymmetricRelativeDepthDisagreement"',
            '"finite-pixel-centres-only"',
            '"solverPolicy"',
            '"relativeSolutionChange"',
            '"normalizedWeightChange"',
            '"firstOrderOptimality"',
            '"cycle-midpoint-fixed-scale-huber"',
        ):
            self.assertIn(contract_field, worker)
        self.assertIn(
            "same-color-adjacent-depth-consensus-v2",
            worker,
        )
        self.assertIn(
            "evidence-bounded-observed-cell-graph-with-piecewise-grade-bank-fallback-v1",
            trainer,
        )

    def test_sign_evidence_is_receipted_and_published_with_hashes(self) -> None:
        worker = (RECONSTRUCTION / "servo_worker.py").read_text(encoding="utf-8")
        self.assertIn('semantics.get("signEvidence")', worker)
        self.assertIn("validate_sign_evidence_artifacts(", worker)
        self.assertRegex(
            worker,
            r"(?s)artifacts\s*=\s*\[.*\*sign_evidence_files.*\]",
        )
        for artifact in (
            '"sign-evidence.json"',
            '"sign-proposals"',
            '"sign-atlases"',
            '"signArtifacts"',
            "published_sign_hashes",
        ):
            self.assertIn(artifact, worker)
        self.assertIn('"regulatoryClassVerified": False', worker)
        self.assertIn('"textVerified": False', worker)
        self.assertIn('"containsGeneratedPixels": False', worker)

    def test_observed_sky_is_environment_not_finite_gaussian_geometry(self) -> None:
        worker = (RECONSTRUCTION / "servo_worker.py").read_text(encoding="utf-8")
        trainer = (RECONSTRUCTION / "servo_train.py").read_text(encoding="utf-8")
        priors = (RECONSTRUCTION / "servo_priors.py").read_text(encoding="utf-8")
        method = (
            "observed-oneformer-temporally-confirmed-sky-alpha-mean-plus-"
            "interior-tail-bce-v4"
        )

        self.assertRegex(worker, r'"semanticSkyOpacityWeight"\s*:\s*0\.10')
        self.assertIn(method, worker)
        self.assertIn(method, trainer)
        self.assertIn("def semantic_sky_opacity_loss", trainer)
        self.assertIn("semantic_sky_opacity_weight * sky_opacity_loss", trainer)
        self.assertIn("certifiedSkyEvidence", worker)
        self.assertIn("certifiedSkyEvidence", trainer)
        self.assertIn("build_certified_sky_evidence", priors)
        self.assertIn("rotation_only_semantic_correspondence", priors)
        for field in (
            '"semanticSkyOpacitySteps"',
            '"semanticSkyOpacitySamples"',
            '"recentSemanticSkyOpacityLoss"',
            '"semanticSkyOpacityTailThreshold"',
            '"semanticSkyOpacityTailWeight"',
            '"semanticSkyOpacityTailBceEpsilon"',
            '"semanticSkyOpacityTailErosionMethod"',
            '"semanticSkyOpacityTailErosionRadius"',
            '"maximumSkyAlphaP95"',
            '"maximumSkyAlphaAboveTenPercentFraction"',
            '"maximumViewSkyAlphaP95"',
        ):
            self.assertIn(field, worker)
            if field.startswith('"semantic') or field.startswith('"recent'):
                self.assertIn(field, trainer)

    def test_directional_sky_evidence_is_receipted_and_published(self) -> None:
        worker = (RECONSTRUCTION / "servo_worker.py").read_text(encoding="utf-8")
        priors = (RECONSTRUCTION / "servo_priors.py").read_text(encoding="utf-8")
        trainer = (RECONSTRUCTION / "servo_train.py").read_text(encoding="utf-8")
        audit = (RECONSTRUCTION / "servo_audit_world.py").read_text(encoding="utf-8")
        environment = (RECONSTRUCTION / "servo_environment.py").read_text(
            encoding="utf-8"
        )
        for text in (
            '"observedDirectionalEnvironment"',
            "validate_observed_directional_environment_artifact",
            "observed-sky-equirectangular.png",
        ):
            self.assertIn(text, worker)
        self.assertIn("build_observed_directional_environment", priors)
        self.assertIn("directional_raster_background", trainer)
        self.assertIn("directional_raster_background", audit)
        self.assertIn("containsGeneratedPixels", environment)
        self.assertIn("no-inpainting", environment)

    def test_geometry_stage_is_presented_between_pose_and_training(self) -> None:
        prepare = (
            REPOSITORY / "src" / "ui" / "workspaces" / "PrepareWorkspace.qml"
        ).read_text(encoding="utf-8")
        pose = prepare.index('{ "id": "pose", "label": "Camera solve" }')
        geometry = prepare.index(
            '{ "id": "geometry", "label": "Road geometry" }'
        )
        train = prepare.index('{ "id": "train", "label": "Gaussian fit" }')
        self.assertLess(pose, geometry)
        self.assertLess(geometry, train)


if __name__ == "__main__":
    unittest.main()
