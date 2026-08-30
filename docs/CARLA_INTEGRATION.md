# CARLA integration

Servo treats CARLA as an external, registered physics runtime. The supported
integration is the packaged Windows release of CARLA 0.9.16; CARLA source and
Unreal Engine are not built or vendored. CARLA owns deterministic time, vehicle
physics, road contact, collision and lane events, actors, and generated sensor
truth. Servo owns reconstructed appearance, coordinate alignment, policy
contracts, run control, evidence, and promotion decisions. A Gaussian splat is
never used as collision geometry.

The local worker runs synchronous fixed-timestep ticks independently of the UI.
It spawns `vehicle.lincoln.mkz_2020`, keeps CARLA autopilot off, obtains a policy
action, validates it, records raw and applied controls, and calls
`apply_control`. It never teleports the ego. At the sealed route terminal it
retains route curvature, applies full physical braking until stopped, writes a
hash-bound terminal receipt, and terminates. Evidence replay loops once rather
than silently restarting.

Observation sources are explicit: `carla-rgb`, `servo-gaussian`, or `hybrid`.
Missing exact frames, inadequate Gaussian coverage, invalid alignment, or an
unvalidated map fail closed as infrastructure-invalid. There is no silent
renderer or policy fallback.

The desktop exposes two explicit, separate evidence views:

- **Native CARLA** is the uncomposited CARLA/Unreal chase camera and is the
  default live and replay view.
- **Actual T5 world** is the published interactive five-tile Gaussian world.
  CARLA telemetry can be attached for route inspection, but the view is never
  described as spatially unified CARLA/Gaussian geometry.

The former depth-aware RGB/instance composite is retained only as a sealed
forensic artifact. Its API endpoint returns `410 Gone`, its integration status
is `rejected`, and the desktop does not offer it as a replay or submission view.

The evidence API emits a `visual_integration` verdict for every retained run,
and new runs persist the same fields as `visual_integration_receipt`. For the
current T5 path it states `gaussian_appearance_loaded_as_carla_geometry=false`,
`unified_scene=false`, and `collision_validated=false`. A passing physics gate
therefore proves CARLA contact, gravity, control, and sensor execution only; it
does not validate the reconstructed Gaussian world as a CARLA map.

Artifacts live under `SERVO_SIMULATION_ROOT` (the desktop launcher defaults to
`D:\Servo\simulations`) in per-session directories. Manifests are canonical-JSON
sealed; events are append-only; telemetry, controls, evidence, worker logs,
previews, and cleanup receipts are durable.

Current bounded scope is one junction-free inferred corridor. The
one-pedestrian profile spawns an owned CARLA walker inside the sealed 3.5 m T5
lane, applies bounded `WalkerControl`, verifies surface contact after warm-up
and at the terminal frame, records activation/collision events, and destroys
the actor in cleanup. There is no traffic-light scenario yet.

## Verified CARLA runs attached to the accepted T5 visual route (2026-08-30)

Both runs below use the route and appearance evidence from
`yosemite-t5-hybrid-full-route-v1-20260828`, not the rejected Final v2, with
CARLA 0.9.16 and the local DriveMA-2B checkpoint.

Successful no-traffic snow session: `sim-6291857fc6c84f13`.

- Route completion: **94.26%** and a verified terminal stop
- Collisions: **0**; lane events: **1**
- Policy cameras: `front_left`, `front`, `front_right`
- Policy: `Local DriveMA-2B (Qwen3.5-2B)`, checkpoint
  `sha256:f7342f9c1dd3b32f61ace5ee3f582f2eb8bea4aca9212fd879a4a3ce2dbfc3a8`
- Snow accumulation: **90%**, tire-friction multiplier **0.478**
- CARLA gravity reference: **9.81 m/s²**; measured initial IMU p50:
  **9.756 m/s²**
- `ground_contact_pass=true`, `physics_gate_pass=true`
- Final speed: **0.056 m/s**, throttle **0**, brake **1**, hand brake **true**
- Terminal braking was physically applied for **12** synchronous frames
- World execution hash:
  `sha256:82be13a5192981ba29ea7aa9d03117ed477acf79fe6d199b806cbcbf58b04c9e`

Pedestrian challenge: `sim-40185a19d24e45a9`. The walker stayed grounded
(terminal vertical drift **0.0021 m**) and DriveMA collided with actor 26 at
53.86% route progress. Servo recorded `outcome=collision` and
`failure_class=collision_pedestrian`; this is useful failure evidence, not a
pass. Cleanup destroyed all nine owned actors without error.

The desktop validates persisted session identities before attaching. An empty,
wrong-world, or rejected-v2 session cannot impersonate the accepted visual route.

These are real CARLA/Unreal physics runs, but they are not collision validation
of the reconstructed Gaussian world. T5 scale and road structure remain
inferred; `collisionValidated=false`. Snow appearance provenance remains
`generated-inferred-surface`, and `climatenerf_qualified=false`.
