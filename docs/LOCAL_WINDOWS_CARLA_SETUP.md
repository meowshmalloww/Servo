# Local Windows CARLA setup

1. Extract the packaged CARLA 0.9.16 Windows release. Do not use the source checkout, Docker, WSL, or an Unreal source build.
2. Register it for one launch:

   ```powershell
   .\Start-Servo.ps1
   ```

   Alternatively set `SERVO_CARLA_ROOT`, or use the persisted runtime path/API.
3. Run the machine-readable static preflight:

   ```powershell
   python -m tools.realityci.simulation.carla.discovery --carla-root '.\runtime\carla\CARLA_0.9.16'
   ```

The root must contain `CarlaUE4.exe`, `PythonAPI`, an importable 0.9.16 Python package/wheel/egg, and (for the oracle) bundled BehaviorAgent modules. Servo verifies executable/API identities and rejects version mismatches. The optional full preflight launches an owned server, loads a small map, spawns a vehicle and camera, receives a non-empty frame, cleans actors, and stops only that owned server.

After extraction and successful verification, the downloaded ZIP and any CARLA source checkout are not used by Servo and may be archived or removed. Keep the extracted packaged runtime at the path registered in `simulations/runtime/carla/settings.json`. The packaged Unreal executable and cooked assets are intentionally external runtime data; the integration, lifecycle, policy, world-generation, API, UI, and test code all live in the Servo repository.

From Servo, open Worlds, select a published world, enter the scale/corridor fields, choose Prepare for CARLA, and wait for the CARLA validation badge. Start Drive remains disabled unless the API, runtime, executable-world bundle, route, and policy are ready. Runs can reattach to a durable `sim-…` session.
