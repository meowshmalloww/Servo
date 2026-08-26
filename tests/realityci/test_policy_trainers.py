from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import torch

from tools.realityci.policy.torch_perception import (
    HazardCNN,
    TorchOcclusionPerceptionAdapter,
    load_checkpoint_file,
    save_checkpoint_file,
)
from tools.realityci.hashing import HashMismatch
from tools.realityci.policy.base import SensorPacket
from tools.realityci.trainers import (
    TorchBehaviorCloningTrainer,
    TrainingRequest,
    build_dataset,
    hazard_label,
)
from tools.realityci.trainers.dataset import LabeledDataset, LabeledSample
from tools.realityci.schemas.training import TrainingLimits

from test_runner import make_manifest


def test_checkpoint_roundtrip_hash_and_tamper(tmp_path: Path) -> None:
    model = HazardCNN()
    metadata = {"input_spec": "rgb-1x96x160+ego-speed", "decision_threshold": 0.5}
    path = tmp_path / "ck.pt"
    digest_a = save_checkpoint_file(path, model.state_dict(), metadata)

    loaded_model, loaded_meta, digest_b = load_checkpoint_file(path)
    assert digest_a == digest_b
    assert loaded_meta["decision_threshold"] == 0.5
    for key, value in model.state_dict().items():
        assert torch.equal(loaded_model.state_dict()[key], value)

    blob = bytearray(path.read_bytes())
    blob[-40] ^= 0xFF
    path.write_bytes(bytes(blob))
    mutated_digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    assert mutated_digest != digest_a


def test_adapter_deterministic_inference(tmp_path: Path) -> None:
    torch.manual_seed(0)
    adapter = TorchOcclusionPerceptionAdapter()
    state = adapter.state_dict()
    path = tmp_path / "m.pt"
    save_checkpoint_file(path, state, {"decision_threshold": 0.5})

    loaded = TorchOcclusionPerceptionAdapter(path)
    frame = np.zeros((96, 160, 3), dtype=np.uint8)
    packet = SensorPacket(time_s=0.0, ego_speed_mps=10.0, frame_rgb=frame)
    risk_one = loaded.observe(packet)
    risk_two = loaded.observe(packet)
    assert 0.0 <= risk_one <= 1.0
    assert risk_one == risk_two
    assert loaded.descriptor.checkpoint_sha256.startswith("sha256:")
    with pytest.raises(ValueError):
        loaded.set_decision_threshold(1.5)


def test_hazard_labels_match_ground_truth() -> None:
    occluded = make_manifest()
    clear = make_manifest(occluder=None)

    cross_s = occluded.occluder.position_s_m + 6.0
    assert hazard_label(
        manifest=occluded, elapsed_s=0.2, ego_front_s=20.0, ego_speed_mps=13.0,
        cross_s=cross_s, visible=False,
    ) is False

    ped_visible_t = 2.0
    clear_cross = (clear.route.start_s_m + clear.route.end_s_m) / 2.0
    assert hazard_label(
        manifest=clear, elapsed_s=ped_visible_t,
        ego_front_s=clear_cross - 10.0,
        ego_speed_mps=13.4, cross_s=clear_cross,
        visible=True,
    ) is True

    empty = make_manifest(pedestrian=None)
    assert hazard_label(
        manifest=empty, elapsed_s=1.0, ego_front_s=25.0, ego_speed_mps=13.0,
        cross_s=35.0, visible=True,
    ) is False


def test_build_dataset_produces_both_classes() -> None:
    manifests = [
        make_manifest(seed=21),
        make_manifest(seed=22),
        make_manifest(seed=23, occluder=None),
    ]
    dataset = build_dataset(manifests, max_samples_per_scenario=12)
    assert len(dataset) > 0
    assert dataset.positive_count >= 1
    sample = dataset.samples[0]
    assert sample.frame_rgb.shape == (96, 160, 3)
    assert sample.frame_rgb.dtype == np.uint8


def _tiny_labeled_dataset(positive_frames: int, negative_frames: int, seed: int) -> LabeledDataset:
    rng = np.random.default_rng(seed)
    samples = []
    bright = np.full((96, 160, 3), 200, dtype=np.uint8)
    dark = np.full((96, 160, 3), 30, dtype=np.uint8)
    for i in range(positive_frames):
        noise = rng.integers(0, 6, size=bright.shape, dtype=np.uint8)
        frame=np.clip(bright.astype(int) + noise, 0, 255).astype(np.uint8); samples.append(LabeledSample(frame, frame.copy(), 10.0, 1, float(i), seed))
    for i in range(negative_frames):
        noise = rng.integers(0, 6, size=dark.shape, dtype=np.uint8)
        frame=np.clip(dark.astype(int) + noise, 0, 255).astype(np.uint8); samples.append(LabeledSample(frame, frame.copy(), 10.0, 0, float(i), seed))
    return LabeledDataset(samples=tuple(samples))


def test_trainer_learns_separable_task_and_changes_weights(tmp_path: Path) -> None:
    train = _tiny_labeled_dataset(24, 24, seed=1)
    val = _tiny_labeled_dataset(8, 8, seed=2)
    limits = TrainingLimits(
        max_epochs=8, max_wall_time_s=120.0, max_samples=10_000, early_stop_patience=6
    )
    request = TrainingRequest(dataset=train, validation_dataset=val, baseline_checkpoint_path=None, limits=limits)
    result = TorchBehaviorCloningTrainer().train(request, tmp_path)

    best = max(result.metrics_history, key=lambda point: point["epoch"])
    assert best["val_accuracy"] > 0.9
    artifact = result.checkpoint_artifact
    assert artifact.weights_differ_from_parent is True
    assert artifact.load_verified is True
    assert artifact.parent_checkpoint_sha256 is None
    from tools.realityci.schemas.base import verify_seal

    verify_seal(artifact)
    assert Path(artifact.uri).is_file()


def test_trainer_from_baseline_changes_checkpoint_hash(tmp_path: Path) -> None:
    torch.manual_seed(3)
    base_path = tmp_path / "base.pt"
    save_checkpoint_file(base_path, HazardCNN().state_dict(), {"decision_threshold": 0.5})
    parent_sha = "sha256:" + __import__("hashlib").sha256(base_path.read_bytes()).hexdigest()

    train = _tiny_labeled_dataset(16, 16, seed=4)
    val = _tiny_labeled_dataset(6, 6, seed=5)
    limits = TrainingLimits(max_epochs=3, max_wall_time_s=60.0, max_samples=10_000, early_stop_patience=3)
    request = TrainingRequest(
        dataset=train, validation_dataset=val, baseline_checkpoint_path=base_path, limits=limits
    )
    result = TorchBehaviorCloningTrainer().train(request, tmp_path)
    assert result.checkpoint_artifact.parent_checkpoint_sha256 == parent_sha
    assert result.checkpoint_artifact.checkpoint_sha256 != parent_sha


def test_trainer_rejects_invalid_requests(tmp_path: Path) -> None:
    limits = TrainingLimits(max_epochs=1, max_wall_time_s=10.0, max_samples=100, early_stop_patience=1)
    empty = LabeledDataset(samples=())
    request = TrainingRequest(dataset=empty, validation_dataset=_tiny_labeled_dataset(2, 2, 1), baseline_checkpoint_path=None, limits=limits)
    with pytest.raises(ValueError):
        request.validate()
