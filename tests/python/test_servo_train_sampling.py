from __future__ import annotations

import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPOSITORY = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


servo_train = load_module(
    "servo_train_sampling", REPOSITORY / "tools" / "reconstruction" / "servo_train.py"
)
servo_worker = load_module(
    "servo_worker_sampling", REPOSITORY / "tools" / "reconstruction" / "servo_worker.py"
)


def records(count: int) -> list[SimpleNamespace]:
    anchor_counts = [12] * count
    anchor_counts[count // 2] = 1
    return [
        SimpleNamespace(
            name=f"video-000/{index:08d}.png",
            sparse_depths=[0.0] * anchor_counts[index],
        )
        for index in range(count)
    ]


class TrainingSamplingTests(unittest.TestCase):
    def test_capture_health_keeps_pose_cameras_but_filters_appearance_fit(self) -> None:
        source_records = records(32)
        selected = [record.name for index, record in enumerate(source_records) if index % 2 == 0]
        dataset = SimpleNamespace(
            records=source_records,
            train_indices=[index for index in range(32) if index not in {4, 12, 20}],
            validation_indices={4, 12, 20},
            sequence_groups=[list(range(32))],
        )
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "capture-health.json"
            receipt_path.write_text(
                json.dumps(
                    {
                        "schema": servo_train.CAPTURE_HEALTH_SCHEMA,
                        "selection": {
                            "method": servo_train.CAPTURE_HEALTH_SELECTION_METHOD,
                            "selectedCount": len(selected),
                            "selectedFrames": selected,
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = {
                "diagnosticProvenance": {"nonPublishable": True},
                "appearanceFrameSelection": {
                    "schema": servo_train.APPEARANCE_FRAME_SELECTION_SCHEMA,
                    "method": servo_train.CAPTURE_HEALTH_SELECTION_METHOD,
                    "captureHealthPath": str(receipt_path),
                    "captureHealthSha256": servo_train.sha256_file(receipt_path),
                },
            }

            receipt = servo_train.apply_appearance_frame_selection(config, dataset)

        self.assertIsNotNone(receipt)
        self.assertEqual(receipt["registeredFrames"], 32)
        self.assertEqual(receipt["appearanceFrames"], 16)
        self.assertEqual(receipt["poseOnlyFrames"], 16)
        self.assertEqual(dataset.validation_indices, {4, 12, 20})
        self.assertEqual(set(dataset.appearance_indices), set(range(0, 32, 2)))
        self.assertTrue(set(dataset.train_indices).isdisjoint(dataset.validation_indices))
        self.assertEqual(
            set(dataset.training_sampling_plan.weights), set(dataset.train_indices)
        )

    def test_target_cap_freezes_growth_without_disabling_screen_space_pruning(self) -> None:
        strategy = SimpleNamespace(
            grow_grad2d=0.0008,
            grow_scale2d=0.05,
            refine_stop_iter=4_500,
        )

        servo_train.freeze_density_growth_at_target(strategy)

        self.assertTrue(math.isinf(strategy.grow_grad2d))
        self.assertTrue(math.isinf(strategy.grow_scale2d))
        # gsplat runs its prune pass only while this remains in the future.
        self.assertEqual(strategy.refine_stop_iter, 4_500)

    def test_fixed_early_density_window_is_sealed_to_diagnostics(self) -> None:
        main_fit_stop = 28_000
        diagnostic = {
            "diagnosticProvenance": {
                "schema": servo_train.DIAGNOSTIC_PROVENANCE_SCHEMA,
                "nonPublishable": True,
            }
        }
        arguments = {
            "policy": servo_train.DIAGNOSTIC_FIXED_DENSITY_REFINEMENT_POLICY,
            "stop_iter": servo_train.DIAGNOSTIC_FIXED_DENSITY_REFINEMENT_STOP,
            "main_fit_stop_iter": main_fit_stop,
            "coarse_steps": 1_000,
            "dense_geometry_start": 500,
        }
        self.assertTrue(
            servo_train.supported_density_refinement_contract(diagnostic, **arguments)
        )
        self.assertFalse(
            servo_train.supported_density_refinement_contract({}, **arguments)
        )
        self.assertTrue(
            servo_train.supported_density_refinement_contract(
                {},
                policy=servo_train.DENSITY_REFINEMENT_POLICY,
                stop_iter=main_fit_stop,
                main_fit_stop_iter=main_fit_stop,
                coarse_steps=1_000,
                dense_geometry_start=500,
            )
        )

    def test_validation_split_keeps_endpoint_windows_in_training(self) -> None:
        indices = list(range(373))
        heldout = servo_train.bracketed_validation_indices(
            indices,
            endpoint_guard=servo_train.ENDPOINT_SAMPLING_WINDOW,
        )

        self.assertEqual(heldout, servo_train.bracketed_validation_indices(
            indices,
            endpoint_guard=servo_train.ENDPOINT_SAMPLING_WINDOW,
        ))
        self.assertNotIn(4, heldout)
        self.assertNotIn(372, heldout)
        self.assertIn(12, heldout)
        self.assertIn(364, heldout)
        self.assertTrue(all(8 <= index < len(indices) - 8 for index in heldout))
        for index in heldout:
            self.assertNotIn(index - 1, heldout)
            self.assertNotIn(index + 1, heldout)

    def test_weighted_epoch_is_deterministic_and_oversamples_endpoints(self) -> None:
        source_records = records(24)
        train_indices = list(range(24))
        plan = servo_train.build_training_sampling_plan(
            source_records,
            train_indices,
            [train_indices],
        )
        self.assertEqual(plan.weights[0], 2)
        self.assertEqual(plan.weights[23], 2)
        self.assertEqual(plan.weights[12], 4)
        self.assertEqual(len(plan.epoch_slots), sum(plan.weights.values()))

        first = servo_train.DeterministicWeightedEpochSampler(
            plan.epoch_slots, "sha256:test", "main-fit"
        )
        second = servo_train.DeterministicWeightedEpochSampler(
            plan.epoch_slots, "sha256:test", "main-fit"
        )
        sequence_a = [first.index(offset) for offset in range(len(plan.epoch_slots) * 3)]
        sequence_b = [second.index(offset) for offset in range(len(plan.epoch_slots) * 3)]
        self.assertEqual(sequence_a, sequence_b)
        for index, weight in plan.weights.items():
            self.assertEqual(sequence_a.count(index), weight * 3)

    def test_worker_binds_sampling_and_screen_refinement_receipts(self) -> None:
        source_records = records(24)
        cameras = {
            "cameras": [{"image": record.name} for record in source_records],
            "validationImages": [source_records[9].name],
        }
        train_indices = [index for index in range(24) if index != 9]
        plan = servo_train.build_training_sampling_plan(
            source_records,
            train_indices,
            [list(range(24))],
        )
        total = 27_000
        sampler = servo_train.DeterministicWeightedEpochSampler(
            plan.epoch_slots, "sha256:fixture", "main-fit"
        )
        visits = [0] * 24
        for offset in range(total):
            visits[sampler.index(offset)] += 1
        endpoint_visits = [visits[index] for index in plan.endpoint_indices]
        per_image = [
            {
                "image": source_records[index].name,
                "visits": visits[index],
                "weight": plan.weights[index],
                "sparseAnchors": plan.sparse_anchor_counts[index],
                "endpoint": index in plan.endpoint_indices,
            }
            for index in train_indices
        ]
        config = {
            "maxSteps": 30_000,
            "finalFitSteps": 3_000,
            "mainSamplingPolicy": servo_worker.MAIN_SAMPLING_POLICY,
            "endpointSamplingWindow": 8,
            "endpointSamplingMultiplier": 2,
            "maximumSparseAnchorMultiplier": 4,
            "screenSpaceRefinementPolicy": servo_worker.SCREEN_SPACE_REFINEMENT_POLICY,
            "densityRefinementPolicy": servo_worker.DENSITY_REFINEMENT_POLICY,
            "growScale2d": 0.05,
            "pruneScale2d": 0.15,
            "refineScale2dStopIter": 27_000,
        }
        metrics = {
            "heldoutEvaluationStep": total,
            "screenSpaceRefinement": {
                "policy": servo_worker.SCREEN_SPACE_REFINEMENT_POLICY,
                "densityRefinementPolicy": servo_worker.DENSITY_REFINEMENT_POLICY,
                "growScale2d": 0.05,
                "pruneScale2d": 0.15,
                "stopIter": 27_000,
                "actualStopIter": 27_000,
                "growthFrozenAtTarget": True,
                "growthCapPolicy": servo_worker.DENSITY_GROWTH_CAP_POLICY,
                "radiusNormalization": "max-image-dimension",
            },
            "mainSampling": {
                "policy": servo_worker.MAIN_SAMPLING_POLICY,
                "endpointWindow": 8,
                "endpointMultiplier": 2,
                "maximumSparseAnchorMultiplier": 4,
                "medianSparseAnchors": plan.median_sparse_anchors,
                "epochSlots": len(plan.epoch_slots),
                "epochs": total / len(plan.epoch_slots),
                "totalVisits": total,
                "minimumVisits": min(visits[index] for index in train_indices),
                "maximumVisits": max(visits[index] for index in train_indices),
                "endpointImageCount": len(endpoint_visits),
                "minimumEndpointVisits": min(endpoint_visits),
                "maximumEndpointVisits": max(endpoint_visits),
                "perImage": per_image,
            },
        }

        servo_worker.validate_training_coverage_contract(config, metrics, cameras)

        metrics["mainSampling"]["perImage"][0]["endpoint"] = False
        with self.assertRaises(servo_worker.WorkerError):
            servo_worker.validate_training_coverage_contract(config, metrics, cameras)

        metrics["mainSampling"]["perImage"][0]["endpoint"] = True
        metrics["mainSampling"]["policy"] = "unbound-policy"
        with self.assertRaises(servo_worker.WorkerError):
            servo_worker.validate_training_coverage_contract(config, metrics, cameras)


if __name__ == "__main__":
    unittest.main()
