"""Detached CARLA simulation worker CLI."""

from __future__ import annotations

import argparse
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from ...hashing import sha256_file
from ...schemas.driving import (
    DrivingFailureClass,
    DrivingOutcome,
    DrivingRunEvidence,
    DrivingRunMetrics,
)
from ...schemas.simulation import SimulationSessionState
from ..session_store import SessionStore, atomic_write_json
from .discovery import DiscoveryResult, port_available
from .process_manager import CarlaProcessManager
from .runner import CarlaSimulationRunner


def run_manifest(manifest_path: Path) -> int:
    manifest_path = manifest_path.resolve()
    session_root = manifest_path.parent
    store = SessionStore(session_root.parent, session_root.name)
    manager = None
    owned_server = False
    manifest = None
    try:
        manifest = store.load_manifest()
        manager = CarlaProcessManager(
            Path(manifest.runtime.root),
            store.root / "runtime" / "carla" / "server.json",
        )
        store.transition(SimulationSessionState.PREFLIGHTING, "worker validated sealed manifest")
        store.record_worker(os.getpid(), ["python", "-m", "tools.realityci.simulation.carla.worker", "--manifest", str(manifest_path)])
        if port_available(manifest.runtime.rpc_port):
            store.transition(SimulationSessionState.LAUNCHING_SERVER, "launching owned packaged CARLA server")
            runtime = DiscoveryResult(
                status="ready", ready=True, expected_version="0.9.16",
                root=manifest.runtime.root, executable=manifest.runtime.executable,
                executable_sha256=manifest.runtime.executable_sha256,
                python_api_path=manifest.runtime.python_api_path,
                python_api_sha256=manifest.runtime.python_api_sha256,
                client_version=manifest.runtime.client_version,
                server_version=None, agents_available=manifest.runtime.agents_available,
                rpc_port_available=True, maps=manifest.runtime.maps, errors=(), warnings=(),
            )
            manager.launch(
                runtime,
                require_rendering=manifest.observation.source.value in {"carla-rgb", "hybrid"},
                rpc_port=manifest.runtime.rpc_port,
                traffic_manager_port=manifest.runtime.traffic_manager_port,
            )
            owned_server = True
            deadline = time.monotonic() + 90.0
            last_error = "server did not accept connections"
            while time.monotonic() < deadline:
                try:
                    from .client import connect_verified

                    _, _, _, server_version = connect_verified(
                        manifest.runtime.python_api_path,
                        "127.0.0.1",
                        manifest.runtime.rpc_port,
                        timeout_s=2.0,
                    )
                    manager.record_health(True, server_version)
                    break
                except Exception as exc:
                    last_error = str(exc)
                    time.sleep(0.5)
            else:
                manager.record_health(False, None, last_error)
                raise RuntimeError(f"owned CARLA server failed readiness: {last_error}")
        elif not manager.verify_record():
            raise RuntimeError(
                f"RPC port {manifest.runtime.rpc_port} is occupied by a process Servo does not own"
            )
        CarlaSimulationRunner(manifest, store).run()
        return 0
    except Exception as exc:
        try:
            current = store.state()
            if SimulationSessionState.FAILED in __import__("tools.realityci.simulation.session_store", fromlist=["LEGAL_TRANSITIONS"]).LEGAL_TRANSITIONS.get(current, set()):
                store.transition(SimulationSessionState.FAILED, str(exc))
            message = str(exc)
            normalized = message.lower()
            if "sensor desynchronization" in normalized or "sensor frame" in normalized:
                failure_class = DrivingFailureClass.SENSOR_DESYNCHRONIZATION
            elif "renderer" in normalized or "out of support" in normalized:
                failure_class = DrivingFailureClass.RENDERER_OUT_OF_SUPPORT
            elif "alignment" in normalized or "coordinate" in normalized:
                failure_class = DrivingFailureClass.MAP_ALIGNMENT_FAILURE
            else:
                failure_class = DrivingFailureClass.PHYSICS_WORLD_INVALID
            failure_path = session_root / "worker-failure.json"
            atomic_write_json(
                failure_path,
                {
                    "schema_name": "servo.simulation-infrastructure-failure/v1",
                    "session_id": session_root.name,
                    "infrastructure_invalid": True,
                    "failure_class": failure_class.value,
                    "error": message,
                    "traceback": traceback.format_exc(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            if manifest is not None:
                evidence = DrivingRunEvidence(
                    session_id=manifest.session_id,
                    campaign_id=manifest.campaign_id,
                    executable_world_sha256=manifest.executable_world.content_hash,
                    opendrive_sha256=manifest.executable_world.structure.opendrive_sha256,
                    appearance_sha256=manifest.executable_world.appearance.appearance_sha256,
                    route_sha256=next(route.route_sha256 for route in manifest.executable_world.routes if route.route_id == manifest.route_id),
                    carla_version=manifest.runtime.server_version or manifest.backend_version,
                    carla_executable_sha256=manifest.runtime.executable_sha256,
                    carla_python_api_version=manifest.runtime.client_version,
                    policy=manifest.policy,
                    controller_version="servo-controller/v1",
                    renderer_version=manifest.observation.renderer_version,
                    observation_source=manifest.observation.source,
                    seed=manifest.scenario.seed,
                    metrics=DrivingRunMetrics(
                        simulation_duration_s=0.0,
                        fixed_delta_seconds=manifest.timing.fixed_delta_seconds,
                        frame_count=0,
                        distance_traveled_m=0.0,
                        route_completion=0.0,
                        min_speed_mps=0.0,
                        max_speed_mps=0.0,
                        final_speed_mps=0.0,
                        mean_lateral_error_m=0.0,
                        max_lateral_error_m=0.0,
                        mean_policy_latency_ms=0.0,
                        max_policy_latency_ms=0.0,
                        deadline_misses=0,
                        sensor_sync_failures=1 if failure_class == DrivingFailureClass.SENSOR_DESYNCHRONIZATION else 0,
                        collision_count=0,
                        lane_invasion_count=0,
                        out_of_support_duration_s=0.0,
                    ),
                    outcome=DrivingOutcome.INFRASTRUCTURE_INVALID,
                    failure_class=failure_class,
                    infrastructure_invalid=True,
                    artifact_sha256={"worker-failure.json": sha256_file(str(failure_path))},
                    created_at=datetime.now(timezone.utc),
                )
                atomic_write_json(session_root / "run-evidence.json", evidence.model_dump(mode="json"))
        except Exception:
            pass
        return 1
    finally:
        if owned_server and manager is not None:
            try:
                manager.stop()
            except Exception as exc:
                atomic_write_json(session_root / "server-cleanup-failure.json", {"error": str(exc)})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    return run_manifest(parser.parse_args(argv).manifest)


if __name__ == "__main__":
    raise SystemExit(main())
