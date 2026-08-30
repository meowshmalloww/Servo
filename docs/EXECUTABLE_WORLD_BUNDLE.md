# Executable world bundle

A published `servo.gaussian-world/v1` is appearance evidence only. “Prepare for CARLA” creates a separate `execution/carla-v1` companion containing `map.xodr`, `route.json`, `alignment.json`, `validation-report.json`, and a sealed `execution-manifest.json`.

Preparation requires an explicit positive metres-per-Servo-unit anchor, provenance (`measured` or `inferred`), uncertainty, lane width, driving side, route direction, and the camera-path role. Registered camera centers are smoothed within a bounded deviation and converted to a junction-free single corridor. The resulting OpenDRIVE and road topology are tagged inferred, never measured.

Servo uses X right, Y up, and -Z forward. CARLA uses X forward, Y right, and Z up. The bundle stores both row-major 4x4 transforms, checks their inverse round trip, and stores route geometry in CARLA metres. `ready_for_carla` can only become true after structural checks and an actual CARLA generated-world dry-run succeed.

The first corridor supports lane following and small recovery offsets. It does not establish general road geometry, junction semantics, production localization, or safe urban driving.
