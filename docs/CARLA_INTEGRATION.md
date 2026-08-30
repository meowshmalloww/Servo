# CARLA integration

Servo treats CARLA as an external, registered physics runtime. The supported integration is the packaged Windows release of CARLA 0.9.16; CARLA source and Unreal Engine are not built or vendored. CARLA owns deterministic time, vehicle physics, road contact, collision and lane events, actors, and generated sensor truth. Servo owns reconstructed appearance, coordinate alignment, policy contracts, run control, evidence, and promotion decisions. A Gaussian splat is never used as collision geometry.

The local worker runs synchronous fixed-timestep ticks independently of the UI. It spawns `vehicle.lincoln.mkz_2020`, calls `set_autopilot(False)`, obtains a policy action, validates it, records both raw and applied controls, and calls `apply_control`. It never teleports the ego during the loop. HTTP polling only reads a decimated `live-state.json`.

Observation sources are explicit: `carla-rgb`, `servo-gaussian`, or `hybrid`. Missing exact frames, inadequate Gaussian coverage, invalid alignment, or an unvalidated map fail closed and classify the run as infrastructure-invalid rather than a policy failure. There is no silent renderer or policy fallback.

Artifacts live under `SERVO_SIMULATION_ROOT` (the desktop launcher defaults to
`D:\Servo\simulations`) in per-session directories. Manifests are canonical-JSON
sealed; events are append-only and monotonic; telemetry, actions, applied
controls, evidence, worker logs, policy-frame previews, and cleanup receipts are
durable.

Current bounded scope is one junction-free inferred corridor. Dynamic actor
composition is implemented as exact-frame RGB/depth/instance masking in the
renderer; the verified run below uses the no-traffic actor profile so it does
not claim pedestrian or traffic-light validation.

## Verified T5 Final v2 run (2026-08-30)

The integration has now run end to end against
`yosemite-t5-all-full-route-review-v2-20260828` using CARLA 0.9.16 and the
local DriveMA-2B checkpoint. The durable snow session is
`sim-d8e994ae412a481a`.

- Route completion: **99.20%** / **30.43 m**
- Collisions: **0**; lane events: **1**
- Mean/max lateral error: **0.207 m / 0.472 m**
- Policy cameras: `front_left`, `front`, `front_right`
- Policy: `Local DriveMA-2B (Qwen3.5-2B)`, checkpoint
  `sha256:f7342f9c1dd3b32f61ace5ee3f582f2eb8bea4aca9212fd879a4a3ce2dbfc3a8`
- Snow accumulation: **90%**, tire-friction multiplier **0.478**
- CARLA gravity reference: **9.81 m/s²**; measured initial IMU p50:
  **9.769 m/s²**
- `ground_contact_pass=true`, `physics_gate_pass=true`

The desktop replays the synchronized integrated video and exposes the two side
policy cameras. It validates persisted session identities before attaching, so
an interrupted or empty session directory cannot impersonate a completed run.

This is a real CARLA/Unreal physics run, but it is not collision validation of
the reconstructed Gaussian world. T5 scale and road structure remain inferred,
and the Gaussian bundle remains `REVIEW REQUIRED`.
