"""Isolated launcher for the official ClimateNeRF train/render programs.

This module never synthesizes a preview.  It only invokes the audited
ClimateNeRF container and records the exact command, image identity and output
hashes.  Dataset and checkpoint inputs are mounted read-only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Sequence


DEFAULT_IMAGE = "servo-climatenerf:official-2023-cu113-semantic"
EFFECTS = {"clear": None, "smog": "smog", "flood": "water", "snow": "snow"}
MTMT_OVERRIDE = Path(__file__).resolve().parent / "overrides" / "sitecustomize.py"
DATASET_REGISTRY_OVERRIDE = Path(__file__).resolve().parent / "overrides" / "datasets_init.py"
QUALIFICATION_CODE = (
    "import json,torch,tinycudann,vren,torch_scatter,datasets.color_utils;"
    "print(json.dumps({'cuda':torch.cuda.is_available(),"
    "'gpu':torch.cuda.get_device_name(0),'torch':torch.__version__,"
    "'cuda_version':torch.version.cuda}))"
)
QUALIFICATION_TRAIN_WRAPPER = (
    "import os,runpy,sys;"
    "from datasets.base import BaseDataset;"
    "import render as _render;"
    "_upstream_len=BaseDataset.__len__;"
    "_steps=int(os.environ['SERVO_CLIMATE_QUALIFICATION_STEPS']);"
    "BaseDataset.__len__=lambda self: _steps if self.split.startswith('train') else _upstream_len(self);"
    "_render.render_for_test=lambda *_args,**_kwargs: None;"
    "sys.argv=sys.argv[1:];"
    "runpy.run_path('train.py',run_name='__main__')"
)
RENDER_WRAPPER = (
    "import os,runpy,sys,torch;"
    "from pathlib import Path;"
    "import models.rendering as _rendering;"
    "from datasets.base import BaseDataset;"
    "_listdir=os.listdir;"
    "os.listdir=lambda path: [item.name for item in Path(path).rglob('*') if item.is_file()] if Path(path).resolve()==Path('/data/images') else _listdir(path);"
    "_upstream_render=_rendering.render;"
    "_dataset_len=BaseDataset.__len__;"
    "_max_frames=int(os.environ.get('SERVO_CLIMATE_MAX_RENDER_FRAMES','0'));"
    "_effect=os.environ.get('SERVO_CLIMATE_EFFECT','clear');"
    "_checkpoint=torch.load('/servo/checkpoint.ckpt',map_location='cpu') if _effect=='snow' else {};"
    "_snow_keys=tuple(_checkpoint.get('state_dict',_checkpoint).keys()) if _effect=='snow' else ();"
    "assert _effect!='snow' or any('mb_model' in key for key in _snow_keys),"
    "'Official ClimateNeRF snow rendering requires model_with_snow checkpoint components';"
    "del _checkpoint;"
    "BaseDataset.__len__=lambda self: min(_dataset_len(self),_max_frames) if _max_frames>0 and not self.split.startswith('train') else _dataset_len(self);"
    "_rendering.render=lambda *args,**kwargs: {k:v for k,v in _upstream_render(*args,**kwargs).items() if v is not None};"
    "sys.argv=sys.argv[1:];"
    "runpy.run_path('render.py',run_name='__main__')"
)
SNOW_TRAIN_WRAPPER = (
    "import runpy,sys,torch;"
    "_checkpoint=torch.load('/servo/base.ckpt',map_location='cpu');"
    "_hparams=_checkpoint.get('hyper_parameters',{});"
    "assert _hparams.get('render_semantic') is True,"
    "'Official ClimateNeRF snow requires a base scene trained with render_semantic=True';"
    "assert _hparams.get('sem_conf_path') and _hparams.get('sem_ckpt_path'),"
    "'Official ClimateNeRF snow requires audited semantic config/checkpoint provenance';"
    "del _checkpoint;"
    "sys.argv=sys.argv[1:];"
    "runpy.run_path('make_snow.py',run_name='__main__')"
)
FULL_TRAIN_WRAPPER = (
    "import os,runpy,sys;"
    "from pathlib import Path;"
    "import pytorch_lightning.callbacks as _callbacks;"
    "import pytorch_lightning as _lightning;"
    "import render as _render;"
    "_listdir=os.listdir;"
    "os.listdir=lambda path: [item.name for item in Path(path).rglob('*') if item.is_file()] if Path(path).resolve()==Path('/data/images') else _listdir(path);"
    "_checkpoint_init=_callbacks.ModelCheckpoint.__init__;"
    "_trainer_fit=_lightning.Trainer.fit;"
    "_every=int(os.environ['SERVO_CLIMATE_CHECKPOINT_EVERY']);"
    "_callbacks.ModelCheckpoint.__init__=lambda self,*args,**kwargs: _checkpoint_init(self,*args,**{**kwargs,'every_n_epochs':_every});"
    "_lightning.Trainer.fit=lambda self,model,*args,**kwargs: (setattr(model,'update_interval',int(os.environ['SERVO_CLIMATE_DENSITY_UPDATE_INTERVAL'])),setattr(model,'warmup_steps',int(os.environ['SERVO_CLIMATE_WARMUP_STEPS'])),_trainer_fit(self,model,*args,**kwargs))[2];"
    "_render.render_for_test=lambda *_args,**_kwargs: None;"
    "sys.argv=sys.argv[1:];"
    "runpy.run_path('train.py',run_name='__main__')"
)


class ReferenceBackendError(RuntimeError):
    pass


def _resolved_directory(path: Path, name: str) -> Path:
    value = path.resolve()
    if not value.is_dir():
        raise ReferenceBackendError(f"{name} directory is missing: {value}")
    return value


def _resolved_file(path: Path, name: str) -> Path:
    value = path.resolve()
    if not value.is_file():
        raise ReferenceBackendError(f"{name} file is missing: {value}")
    return value


def _mount(source: Path, target: str, readonly: bool = False) -> str:
    value = f"type=bind,source={source},target={target}"
    return value + (",readonly" if readonly else "")


def _runtime_options() -> list[str]:
    override = _resolved_file(MTMT_OVERRIDE, "Servo MTMT fail-closed override")
    registry = _resolved_file(DATASET_REGISTRY_OVERRIDE, "Servo COLMAP-only dataset registry")
    return ["--env", "PYTHONPATH=/servo-overrides",
            "--mount", _mount(override, "/servo-overrides/sitecustomize.py", True),
            "--mount", _mount(registry, "/opt/climatenerf/datasets/__init__.py", True)]


def _image_identity(image: str) -> str:
    result = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
        check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0 or not result.stdout.strip().startswith("sha256:"):
        raise ReferenceBackendError(f"qualified ClimateNeRF image is unavailable: {image}")
    return result.stdout.strip()


def _run(command: Sequence[str], *, log_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", errors="replace") as log:
            log.write(f"\n--- Servo ClimateNeRF invocation {dt.datetime.now(dt.timezone.utc).isoformat()} ---\n")
            log.flush()
            process = subprocess.Popen(
                list(command), text=True, encoding="utf-8", errors="replace",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            assert process.stdout is not None
            for chunk in iter(lambda: process.stdout.read(4096), ""):
                log.write(chunk)
                log.flush()
            returncode = process.wait()
        output = log_path.read_text(encoding="utf-8", errors="replace")
        if returncode != 0:
            tail = "\n".join(output.splitlines()[-30:])
            raise ReferenceBackendError(
                f"ClimateNeRF command failed with exit code {returncode}:\n{tail}")
        return subprocess.CompletedProcess(list(command), returncode, "", "")
    result = subprocess.run(list(command), check=False, text=True,
                            encoding="utf-8", errors="replace",
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(result.stdout, encoding="utf-8")
    if result.returncode != 0:
        tail = "\n".join(result.stdout.splitlines()[-30:])
        raise ReferenceBackendError(
            f"ClimateNeRF command failed with exit code {result.returncode}:\n{tail}")
    return result


def qualify(image: str = DEFAULT_IMAGE) -> dict[str, Any]:
    identity = _image_identity(image)
    command = ["docker", "run", "--rm", "--gpus", "all", *_runtime_options(),
               image, "-c", QUALIFICATION_CODE]
    result = _run(command)
    try:
        runtime = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise ReferenceBackendError("ClimateNeRF qualification returned no JSON") from error
    if runtime.get("cuda") is not True:
        raise ReferenceBackendError("ClimateNeRF qualification did not expose CUDA")
    return {
        "schema_name": "servo.climatenerf-container-qualification/v1",
        "qualified_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "image": image,
        "image_identity": identity,
        "runtime": runtime,
        "modules": ["tinycudann", "vren", "torch_scatter"],
        "mtmt_fail_closed_override_sha256": "sha256:" + hashlib.sha256(
            MTMT_OVERRIDE.read_bytes()).hexdigest(),
        "dataset_registry_override_sha256": "sha256:" + hashlib.sha256(
            DATASET_REGISTRY_OVERRIDE.read_bytes()).hexdigest(),
    }


def _validate_dataset(dataset: Path) -> None:
    _resolved_directory(dataset / "images", "registered image")
    sparse = _resolved_directory(dataset / "sparse" / "0", "COLMAP sparse model")
    for name in ("cameras.bin", "images.bin", "points3D.bin"):
        _resolved_file(sparse / name, f"COLMAP {name}")


def training_command(dataset: Path, output: Path, config: Path, experiment: str,
                     image: str = DEFAULT_IMAGE, extra: Sequence[str] = (),
                     qualification_steps: int | None = None,
                     checkpoint_every: int = 5,
                     density_update_interval: int = 16,
                     warmup_steps: int = 256,
                     semantic_config: Path | None = None,
                     semantic_checkpoint: Path | None = None,
                     semantic_downsample: float = 1.0) -> list[str]:
    dataset = _resolved_directory(dataset, "ClimateNeRF dataset")
    _validate_dataset(dataset)
    config = _resolved_file(config, "ClimateNeRF config")
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", experiment):
        raise ReferenceBackendError("experiment name contains unsafe characters")
    output = output.resolve()
    for name in ("ckpts", "results", "logs"):
        (output / name).mkdir(parents=True, exist_ok=True)
    if qualification_steps is not None and not 1 <= qualification_steps <= 15:
        raise ReferenceBackendError("qualification steps must be in the range 1..15")
    if not 1 <= checkpoint_every <= 80:
        raise ReferenceBackendError("checkpoint interval must be in the range 1..80")
    if not 16 <= density_update_interval <= 512:
        raise ReferenceBackendError("density update interval must be in the range 16..512")
    if not 16 <= warmup_steps <= 1024:
        raise ReferenceBackendError("warmup steps must be in the range 16..1024")
    qualification_options = ([] if qualification_steps is None else [
        "--env", f"SERVO_CLIMATE_QUALIFICATION_STEPS={qualification_steps}"])
    if qualification_steps is None:
        qualification_options += [
            "--env", f"SERVO_CLIMATE_CHECKPOINT_EVERY={checkpoint_every}",
            "--env", f"SERVO_CLIMATE_DENSITY_UPDATE_INTERVAL={density_update_interval}",
            "--env", f"SERVO_CLIMATE_WARMUP_STEPS={warmup_steps}",
        ]
        program = ["-c", FULL_TRAIN_WRAPPER, "train.py"]
    else:
        program = ["-c", QUALIFICATION_TRAIN_WRAPPER, "train.py"]
    semantic_mounts: list[str] = []
    if (semantic_config is None) != (semantic_checkpoint is None):
        raise ReferenceBackendError(
            "semantic config and checkpoint must be supplied together")
    if semantic_config is not None and semantic_checkpoint is not None:
        if not 0.01 <= semantic_downsample <= 1.0:
            raise ReferenceBackendError(
                "semantic downsample must be in the range 0.01..1.0")
        semantic_config = _resolved_file(semantic_config, "mmseg semantic config")
        semantic_checkpoint = _resolved_file(
            semantic_checkpoint, "mmseg semantic checkpoint")
        config_tree = _resolved_directory(
            semantic_config.parent.parent, "mmseg config tree")
        semantic_mounts = [
            "--env", f"SERVO_CLIMATE_SEMANTIC_DOWNSAMPLE={semantic_downsample}",
            "--mount", _mount(config_tree, "/servo/mmseg-configs", True),
            "--mount", _mount(
                semantic_checkpoint, "/servo/semantic/checkpoint.pth", True),
        ]
    return [
        "docker", "run", "--rm", "--gpus", "all", "--shm-size", "8g",
        *_runtime_options(),
        *qualification_options,
        "--mount", _mount(dataset, "/data", True),
        "--mount", _mount(config, "/servo/config.txt", True),
        *semantic_mounts,
        "--mount", _mount(output / "ckpts", "/opt/climatenerf/ckpts"),
        "--mount", _mount(output / "results", "/opt/climatenerf/results"),
        "--mount", _mount(output / "logs", "/opt/climatenerf/logs"),
        image, *program, "--config", "/servo/config.txt",
        "--dataset_name", "colmap", "--root_dir", "/data",
        "--exp_name", experiment, *extra,
    ]


def render_command(dataset: Path, output: Path, config: Path, checkpoint: Path,
                   experiment: str, effect: str, image: str = DEFAULT_IMAGE,
                   plane: Path | None = None, extra: Sequence[str] = (),
                   max_frames: int = 0) -> list[str]:
    if effect not in EFFECTS:
        raise ReferenceBackendError(
            "effect must be clear, smog, flood, or snow; ClimateNeRF does not implement rain")
    dataset = _resolved_directory(dataset, "ClimateNeRF dataset")
    _validate_dataset(dataset)
    config = _resolved_file(config, "ClimateNeRF config")
    checkpoint = _resolved_file(checkpoint, "trained ClimateNeRF checkpoint")
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", experiment):
        raise ReferenceBackendError("experiment name contains unsafe characters")
    output = output.resolve()
    (output / "results").mkdir(parents=True, exist_ok=True)
    if not 0 <= max_frames <= 10000:
        raise ReferenceBackendError("max render frames must be in the range 0..10000")
    command = [
        "docker", "run", "--rm", "--gpus", "all", "--shm-size", "8g",
        *_runtime_options(),
        "--env", f"SERVO_CLIMATE_MAX_RENDER_FRAMES={max_frames}",
        "--env", f"SERVO_CLIMATE_EFFECT={effect}",
        "--mount", _mount(dataset, "/data", True),
        "--mount", _mount(config, "/servo/config.txt", True),
        "--mount", _mount(checkpoint, "/servo/checkpoint.ckpt", True),
        "--mount", _mount(output / "results", "/opt/climatenerf/results"),
    ]
    if effect == "flood":
        if plane is None:
            raise ReferenceBackendError("flood rendering requires a scene-qualified plane.npy")
        plane = _resolved_file(plane, "scene-qualified flood plane")
        command += ["--mount", _mount(plane, "/servo/plane.npy", True)]
    command += [
        image, "-c", RENDER_WRAPPER, "render.py", "--config", "/servo/config.txt",
        "--dataset_name", "colmap", "--root_dir", "/data",
        "--weight_path", "/servo/checkpoint.ckpt", "--exp_name", experiment,
    ]
    if EFFECTS[effect] is not None:
        command += ["--simulate", EFFECTS[effect]]
    if effect == "flood":
        command += ["--plane_path", "/servo/plane.npy"]
    command += list(extra)
    return command


def snow_training_command(dataset: Path, output: Path, config: Path,
                          base_checkpoint: Path, experiment: str,
                          image: str = DEFAULT_IMAGE, epochs: int = 20,
                          metaball_size: float = 5.0e-3,
                          extra: Sequence[str] = ()) -> list[str]:
    """Build the official ClimateNeRF snow components for a semantic scene.

    This invokes the upstream ``make_snow.py`` program.  It deliberately
    rejects RGB-only scene checkpoints: ClimateNeRF derives the ground plane
    from its trained semantic head before fitting the snow metaballs.
    """
    dataset = _resolved_directory(dataset, "ClimateNeRF dataset")
    _validate_dataset(dataset)
    config = _resolved_file(config, "ClimateNeRF config")
    base_checkpoint = _resolved_file(
        base_checkpoint, "semantic ClimateNeRF base checkpoint")
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", experiment):
        raise ReferenceBackendError("experiment name contains unsafe characters")
    if not 1 <= epochs <= 100:
        raise ReferenceBackendError("snow epochs must be in the range 1..100")
    if not 1.0e-5 <= metaball_size <= 0.25:
        raise ReferenceBackendError("snow metaball size must be in the range 1e-5..0.25")
    output = output.resolve()
    for name in ("ckpts", "results", "logs"):
        (output / name).mkdir(parents=True, exist_ok=True)
    return [
        "docker", "run", "--rm", "--gpus", "all", "--shm-size", "8g",
        *_runtime_options(),
        "--mount", _mount(dataset, "/data", True),
        "--mount", _mount(config, "/servo/config.txt", True),
        "--mount", _mount(base_checkpoint, "/servo/base.ckpt", True),
        "--mount", _mount(output / "ckpts", "/opt/climatenerf/ckpts"),
        "--mount", _mount(output / "results", "/opt/climatenerf/results"),
        "--mount", _mount(output / "logs", "/opt/climatenerf/logs"),
        image, "-c", SNOW_TRAIN_WRAPPER, "make_snow.py",
        "--config", "/servo/config.txt", "--dataset_name", "colmap",
        "--root_dir", "/data", "--exp_name", experiment,
        "--weight_path", "/servo/base.ckpt",
        "--weight_path_origin_scene", "/servo/base.ckpt",
        "--mb_size", format(metaball_size, ".12g"),
        "--num_epochs", str(epochs), *extra,
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    qualification = subparsers.add_parser("qualify")
    qualification.add_argument("--output", type=Path)
    train = subparsers.add_parser("train")
    snow_train = subparsers.add_parser("make-snow")
    render = subparsers.add_parser("render")
    for command in (train, snow_train, render):
        command.add_argument("--dataset", required=True, type=Path)
        command.add_argument("--output", required=True, type=Path)
        command.add_argument("--config", required=True, type=Path)
        command.add_argument("--experiment", required=True)
    render.add_argument("--checkpoint", required=True, type=Path)
    render.add_argument("--effect", required=True, choices=sorted(EFFECTS))
    render.add_argument("--plane", type=Path)
    render.add_argument("--max-frames", type=int, default=0)
    snow_train.add_argument("--checkpoint", required=True, type=Path)
    snow_train.add_argument("--epochs", type=int, default=20)
    snow_train.add_argument("--mb-size", type=float, default=5.0e-3)
    train.add_argument("--qualification-steps", type=int)
    train.add_argument("--checkpoint-every", type=int, default=5)
    train.add_argument("--density-update-interval", type=int, default=16)
    train.add_argument("--warmup-steps", type=int, default=256)
    train.add_argument("--semantic-config", type=Path)
    train.add_argument("--semantic-checkpoint", type=Path)
    train.add_argument("--semantic-downsample", type=float, default=1.0)
    args, extra = parser.parse_known_args()
    try:
        if args.operation == "qualify":
            receipt = qualify(args.image)
            text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text, encoding="utf-8")
            print(text, end="")
            return 0
        if args.operation == "train":
            command = training_command(args.dataset, args.output, args.config,
                                       args.experiment, args.image, extra,
                                       args.qualification_steps,
                                       args.checkpoint_every,
                                       args.density_update_interval,
                                       args.warmup_steps,
                                       args.semantic_config,
                                       args.semantic_checkpoint,
                                       args.semantic_downsample)
        elif args.operation == "make-snow":
            command = snow_training_command(
                args.dataset, args.output, args.config, args.checkpoint,
                args.experiment, args.image, args.epochs, args.mb_size, extra)
        else:
            command = render_command(args.dataset, args.output, args.config,
                                     args.checkpoint, args.experiment, args.effect,
                                     args.image, args.plane, extra, args.max_frames)
        log = args.output.resolve() / "logs" / f"{args.operation}-{args.experiment}.log"
        _run(command, log_path=log)
        return 0
    except ReferenceBackendError as error:
        print(json.dumps({"schema_name": "servo.climatenerf-error/v1",
                          "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
