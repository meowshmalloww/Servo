# RealityCI CARLA campaign

The driving campaign boundary is a durable CARLA run-evidence record: runtime/map/world/route/policy identities, seed, synchronized physics metrics, renderer provenance, outcome, failure class, artifacts, and cleanup result. Infrastructure-invalid runs—sensor desynchronization, renderer coverage loss, invalid structure/alignment, or server failure—are excluded from policy diagnosis.

The intended bounded loop is baseline, deterministic failure triage, executed counterfactuals, causal gate, targeted recovery curriculum, oracle-labelled collection, local ServoTinyDrive training, sealed hidden examination, protected regression suite, and deterministic promotion or rejection. The existing Gemini path may propose hypotheses but cannot establish cause or promote a checkpoint.

The local trainer is the only execution mode in this integration. Cloud/A100 and distributed training are not implemented. Resource profiles keep CARLA rendering, headless Gaussian rendering, and training bounded for a laptop GPU; an observation source is never silently reduced or changed.

Run non-CARLA unit tests with `python -m pytest tests/realityci tests/python -q`. Run C++ tests with `ctest --test-dir build --output-on-failure`. CARLA integration tests must be skipped unless a verified packaged runtime exists; skipped tests are not evidence of a real drive.
