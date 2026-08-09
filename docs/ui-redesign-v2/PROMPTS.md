# Servo UI redesign v2

Generated with OpenAI's built-in ImageGen as a coherent desktop-product concept set for a future Qt 6 / QML implementation.

## Shared visual contract

- Professional engineering editor, not a web dashboard.
- Standard title bar and menu bar, followed by five stable task workspaces: Prepare, Simulate, Diagnose, Train, Verify.
- One dominant work surface, one contextual inspector, and one shallow lower drawer. Secondary information stays collapsed until needed.
- Warm graphite shell (`#1b1c1d`) with slightly lighter panels (`#232527`), fine neutral dividers, off-white text, and one oxide-orange accent (`#c77b38`). Green and red appear only for semantic status.
- Compact desktop controls, restrained 0–3 px corner radii, dense but readable typography, persistent spatial layout, and conventional resizable panes.
- Avoid card grids, floating metric tiles, oversized rounded rectangles, pills, gradients, glass effects, neon glows, decorative charts, chat panels, copilot avatars, and marketing-page composition.

## Screen prompt set

### 01 — Prepare

Create a shippable Qt/QML preparation workspace. Use a left project tree for study assets, a central property editor for policy, vehicle, sensors, recordings, simulation settings, and training-adapter boundaries, a right readiness inspector with explicit checks, and a collapsed Problems / Output / Files drawer. Make the primary action `Build world`; keep all configuration in ordinary rows and sections rather than cards.

### 02 — Simulate

Create the primary design-system anchor. Use a left world outliner, a dominant photoreal urban simulation viewport with a compact viewport toolbar, a right selection inspector, and a shallow deterministic timeline. Include transport controls, frame and time readouts, scene entities, sensor/frustum overlays, and restrained orange selection highlights.

### 03 — Diagnose

Create a causal-diagnosis workspace with a searchable failure list on the left, the selected replay in the main viewport, a plain counterfactual-experiments table below it, and a structured Finding inspector on the right. Expose hypothesis, evidence, intervention, and confidence as engineering data. Keep Events / Telemetry / Agent log collapsed; do not add a graph canvas or chatbot.

### 04 — Train

Create an IDE-like targeted-training workspace. Use a job/checkpoint tree on the left, two modest scientific plots and a structured monospaced training log in the center, a Run configuration inspector on the right, and an artifacts table below. Emphasize reproducibility, adapter scope, data recipe, budget, and checkpoint lineage rather than decorative analytics.

### 05 — Verify

Create a release-gate workspace comparing baseline v14 and candidate v18 in synchronized side-by-side replay viewports. Add a regression table for a hidden exam of 48 scenarios and a right Decision inspector. The visible data must agree: generalization 91%, regression 48/48 PASS, passed 48, failed 0, regressed 0, Reality Debt 18.4% to 11.2%, and an enabled `Promote v18` action. State that no regressions were detected and the candidate meets promotion policy.

## Output files

- `01-prepare-workspace.png`
- `02-simulate-workspace.png`
- `03-diagnose-workspace.png`
- `04-train-workspace.png`
- `05-verify-workspace.png`
