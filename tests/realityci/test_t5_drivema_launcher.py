from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

from tools.realityci.driving import launch_t5_drivema


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_launcher_binds_optional_campaign_id(tmp_path: Path, capsys) -> None:
    world = tmp_path / "execution-manifest.json"
    world.write_text("{}", encoding="utf-8")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    with (
        patch.object(
            sys,
            "argv",
            [
                "launch_t5_drivema.py",
                "--world",
                str(world),
                "--campaign-id",
                "campaign-t5-accepted",
            ],
        ),
        patch.object(launch_t5_drivema.urllib.request, "urlopen", fake_urlopen),
        patch.object(launch_t5_drivema.json, "load", return_value={"simulation_id": "sim-test"}),
    ):
        assert launch_t5_drivema.main() == 0

    assert captured["body"]["campaign_id"] == "campaign-t5-accepted"
    assert json.loads(capsys.readouterr().out)["simulation_id"] == "sim-test"


def test_launcher_omits_campaign_id_for_standalone_run(tmp_path: Path) -> None:
    world = tmp_path / "execution-manifest.json"
    world.write_text("{}", encoding="utf-8")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    with (
        patch.object(
            sys,
            "argv",
            ["launch_t5_drivema.py", "--world", str(world)],
        ),
        patch.object(launch_t5_drivema.urllib.request, "urlopen", fake_urlopen),
        patch.object(launch_t5_drivema.json, "load", return_value={"simulation_id": "sim-test"}),
    ):
        assert launch_t5_drivema.main() == 0

    assert "campaign_id" not in captured["body"]


def test_launcher_requests_bounded_real_pedestrian_profile(tmp_path: Path) -> None:
    world = tmp_path / "execution-manifest.json"
    world.write_text("{}", encoding="utf-8")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    with (
        patch.object(
            sys,
            "argv",
            [
                "launch_t5_drivema.py",
                "--world",
                str(world),
                "--dynamic-actor-profile",
                "one-pedestrian",
            ],
        ),
        patch.object(launch_t5_drivema.urllib.request, "urlopen", fake_urlopen),
        patch.object(
            launch_t5_drivema.json,
            "load",
            return_value={"simulation_id": "sim-test"},
        ),
    ):
        assert launch_t5_drivema.main() == 0

    assert captured["body"]["scenario"]["dynamic_actor_profile"] == "one-pedestrian"
