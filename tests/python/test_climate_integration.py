from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tools.climate.dataset_adapter import DatasetError, inspect_world, prepare_dataset
from tools.climate.physics import (
    beer_lambert_transmission,
    deterministic_wave_normals,
    dielectric_fresnel,
    intersect_plane,
    metaball_density,
    refract,
    snow_candidate_confidence,
    water_mask,
)
from tools.climate.reference_backend import (
    ReferenceBackendError,
    render_command,
    snow_training_command,
)
from tools.climate.schemas import SchemaError, validate_weather_bundle, validate_weather_condition
from tools.climate.source_receipt import create_source_receipt, sha256_file
from tools.climate.weather_bundle import PublicationError, bundle_identity, verify_bundle
from tools.climate.worker import ClimateJob
from tools.realityci.schemas.weather import WeatherCondition


HASH = "sha256:" + "a" * 64


class ClimatePhysicsTests(unittest.TestCase):
    def test_smog_transmission_is_monotonic_in_density_and_depth(self) -> None:
        depth = np.array([1.0, 5.0, 20.0])
        low = beer_lambert_transmission(depth, 0.1)
        high = beer_lambert_transmission(depth, 0.5)
        self.assertTrue(np.all(np.diff(low) < 0))
        self.assertTrue(np.all(high < low))

    def test_fresnel_normal_and_grazing_behavior(self) -> None:
        values = dielectric_fresnel(np.array([1.0, 0.5, 0.01]))
        expected_normal = ((1.00029 - 1.333) / (1.00029 + 1.333)) ** 2
        self.assertAlmostEqual(values[0], expected_normal, places=12)
        self.assertGreater(values[2], values[1])
        self.assertGreater(values[1], values[0])

    def test_refraction_and_total_internal_reflection(self) -> None:
        direction = np.array([[0.0, -1.0, 0.0]])
        transmitted, tir = refract(direction, np.array([[0.0, 1.0, 0.0]]))
        self.assertFalse(tir[0])
        np.testing.assert_allclose(transmitted, direction, atol=1e-8)
        grazing = np.array([[0.9, 0.435889894, 0.0]])
        _, tir = refract(grazing, np.array([[0.0, -1.0, 0.0]]), 1.5, 1.0)
        self.assertTrue(tir[0])

    def test_plane_intersection_and_water_mask(self) -> None:
        origins = np.array([[0.0, 1.0, 0.0], [0.0, 1.0, 0.0]])
        rays = np.array([[0.0, -1.0, 0.0], [0.0, 1.0, 0.0]])
        distance, valid = intersect_plane(origins, rays, [0, 0, 0], [0, 1, 0])
        self.assertEqual(distance[0], 1.0)
        np.testing.assert_array_equal(valid, [True, False])
        np.testing.assert_array_equal(water_mask(origins, rays, [2.0, 2.0], [0, 0, 0], [0, 1, 0]), [True, False])

    def test_fft_wave_seed_and_time_are_deterministic(self) -> None:
        args = dict(shape=(24, 32), seed=9, time_s=1.25, wind_direction_deg=35,
                    wind_speed=8, amplitude=0.12, spatial_scale=18)
        first = deterministic_wave_normals(**args)
        second = deterministic_wave_normals(**args)
        later = deterministic_wave_normals(**dict(args, time_s=1.30))
        np.testing.assert_array_equal(first, second)
        self.assertFalse(np.array_equal(first, later))
        np.testing.assert_allclose(np.linalg.norm(first, axis=-1), 1.0, atol=1e-12)

    def test_snow_rejects_vertical_sky_and_sheltered_samples(self) -> None:
        normals = np.array([[0, 1, 0], [1, 0, 0], [0, 1, 0], [0, 1, 0]], dtype=float)
        result = snow_candidate_confidence(normals, [0, 1, 0],
                                           [True, True, False, True], [True, True, True, False])
        np.testing.assert_array_equal(result, [1.0, 0.0, 0.0, 0.0])

    def test_metaball_thickness_is_monotonic(self) -> None:
        points = np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
        thin = metaball_density(points, np.array([[0, 0, 0]]), np.array([0.5]))
        thick = metaball_density(points, np.array([[0, 0, 0]]), np.array([1.0]))
        self.assertGreaterEqual(thick[0], thin[0])
        self.assertGreater(thick[1], thin[1])


class ClimateContractTests(unittest.TestCase):
    def weather_bundle(self) -> dict:
        return {
            "schema_name": "servo.climate-weather/v1", "weather_world_id": "weather-1",
            "base_world_id": "base-1", "base_world_sha256": HASH, "effect": "smog",
            "engine": "climatenerf-reference", "provenance": "generated-climate",
            "climate_source_receipt": {}, "dataset_manifest_sha256": HASH,
            "parameters": {"sigma": 0.1}, "coordinate_system": {}, "scale": {},
            "geometry_readiness": "ready-relative-units", "semantic_readiness": "degraded",
            "normal_readiness": "degraded", "outputs": {}, "validation": {},
            "physics_effects": {"collision_geometry_changed": False, "friction_changed": False,
                                "water_depth_ground_truth": False, "snow_mass_ground_truth": False},
            "created_at": "2026-08-28T00:00:00Z", "producer": {},
        }

    def test_schema_rejects_false_physics_claim(self) -> None:
        manifest = self.weather_bundle()
        manifest["physics_effects"]["friction_changed"] = True
        with self.assertRaises(SchemaError):
            validate_weather_bundle(manifest)

    def test_realityci_condition_separates_visual_and_physical_weather(self) -> None:
        result = WeatherCondition("climatenerf-reference", "smog", {"sigma": 0.1}, 4,
                                  "base", HASH, "climatenerf-reference", "relative").to_dict()
        self.assertIsNone(result["physics_profile"])
        self.assertEqual(result["generated_provenance"], "generated-climate")

    def test_job_transitions_cancellation_and_reattachment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "job"
            job = ClimateJob.create(root, {"effect": "smog"})
            job.transition("preflighting", completed_units=1, total_units=3)
            job.request_cancel()
            attached = ClimateJob.reattach(root)
            self.assertTrue(attached.cancellation_requested())
            self.assertEqual(attached.read()["state"], "preflighting")
            with self.assertRaises(ValueError):
                attached.transition("completed")

    def test_bundle_hash_verification_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "frame.bin").write_bytes(b"observed-derived-output")
            manifest = self.weather_bundle()
            manifest["outputs"] = {"rgb": {"path": "frame.bin", "sha256": sha256_file(root / "frame.bin")}}
            manifest["bundle_sha256"] = bundle_identity(manifest)
            (root / "climate-weather.json").write_text(json.dumps(manifest), encoding="utf-8")
            verify_bundle(root)
            (root / "frame.bin").write_bytes(b"tampered")
            with self.assertRaises(PublicationError):
                verify_bundle(root)

    def test_source_receipt_changes_when_source_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("one", encoding="utf-8")
            first = create_source_receipt(root)
            (root / "README.md").write_text("two", encoding="utf-8")
            second = create_source_receipt(root)
            self.assertNotEqual(first["identity"], second["identity"])

    def test_adapter_fails_closed_for_unverified_non_colmap_world(self) -> None:
        root = Path("runtime/reconstruction/jobs/yosemite-t2b-wildgs-sharp360-scaleguard-v8-20260828/stages/publish/world")
        if not root.is_dir():
            self.skipTest("local demonstration world is not installed")
        audit = inspect_world(root)
        self.assertIn("world quality gate is not accepted/verified", audit["errors"])
        self.assertIn("world has no verified COLMAP sparse reconstruction", audit["errors"])

    def test_reference_backend_rejects_rain_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ReferenceBackendError, "does not implement rain"):
                render_command(root, root / "out", root / "config.txt",
                               root / "model.ckpt", "test", "rain")

    def test_reference_backend_requires_real_colmap_sparse_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / "dataset"
            (dataset / "images").mkdir(parents=True)
            config = root / "config.txt"
            checkpoint = root / "model.ckpt"
            config.write_text("dataset_name = colmap\n", encoding="utf-8")
            checkpoint.write_bytes(b"not-a-real-model")
            with self.assertRaisesRegex(ReferenceBackendError, "COLMAP sparse model"):
                render_command(dataset, root / "out", config, checkpoint,
                               "test", "smog")

    def test_snow_training_uses_official_make_snow_and_read_only_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / "dataset"
            (dataset / "images").mkdir(parents=True)
            sparse = dataset / "sparse" / "0"
            sparse.mkdir(parents=True)
            for name in ("cameras.bin", "images.bin", "points3D.bin"):
                (sparse / name).write_bytes(b"verified-test-fixture")
            config = root / "config.txt"
            checkpoint = root / "semantic.ckpt"
            config.write_text("dataset_name = colmap\n", encoding="utf-8")
            checkpoint.write_bytes(b"command-construction-fixture")

            command = snow_training_command(
                dataset, root / "out", config, checkpoint, "t5-snow")

            self.assertIn("make_snow.py", command)
            self.assertIn("--weight_path_origin_scene", command)
            self.assertIn("--num_epochs", command)
            self.assertIn("20", command)
            checkpoint_mounts = [
                value for value in command
                if "target=/servo/base.ckpt" in value
            ]
            self.assertEqual(len(checkpoint_mounts), 1)
            self.assertTrue(checkpoint_mounts[0].endswith(",readonly"))


if __name__ == "__main__":
    unittest.main()
