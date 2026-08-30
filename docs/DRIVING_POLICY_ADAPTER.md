# Driving policy adapters

Every policy declares its adapter/version, checkpoint URI and SHA-256 when applicable, oracle and privileged-state status, trainability, promotion eligibility, camera IDs, and ego inputs. Unknown schema fields are rejected.

The CARLA BehaviorAgent adapter is a privileged oracle used for reference driving and expert labels. It is never eligible for promotion and still returns an explicit `VehicleControl`; CARLA autopilot remains off. ServoTinyDrive is the bounded trainable adapter: a small temporal CNN consumes declared RGB frames, ego speed, route target, and navigation command and produces a short trajectory. A deterministic controller converts that trajectory to steering/throttle/brake.

Non-oracle observations cannot carry hidden seeds or privileged actor state. The safety guard rejects non-finite, out-of-range, stale, late, conflicting, or excessive-slew actions and applies emergency braking. Raw action and final applied control records remain separate.

The versioned external-local adapter is the boundary intended for DriveMA-2B: it accepts only loopback HTTP, sends the declared front/front-left/front-right RGB bytes with shape/encoding, calibration, synchronized simulation timestamp, speed, acceleration, recent ego poses, route target, navigation command, and previous action, and requires a strict trajectory response before the deadline. This adapter is not enabled as a worker policy until a compatible local service and checkpoint are registered; the requested `D:\VehicleBrain` tree is absent in the current environment.

Dataset manifests hash every sample and keep only a hash receipt for hidden seeds. Training records configuration, dataset identity, environment, checkpoints, metrics, and stop reason. Promotion remains an existing deterministic RealityCI decision; an oracle or LLM cannot override it.
