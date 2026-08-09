# Servo frontend architecture

Servo's desktop interface is a Qt 6.11/QML editor organized around one persistent shell and seven independent workflow workspaces. The current milestone establishes production-oriented UI structure and integration contracts without simulating backend results.

## Source organization

```text
src/
|-- app/
|   `-- main.cpp
`-- ui/
    |-- CMakeLists.txt
    |-- Main.qml
    |-- Session.qml
    |-- Theme.qml
    |-- components/
    |-- icons/
    |-- rendering/
    `-- workspaces/
```

`qt_add_qml_module` packages QML, SVG resources, and the C++ plot item into the `Servo` module. `Main.qml` owns the menu, project context, top navigation, loader, shortcuts, and status strip. Workspace components own only their task layout.

## Visual system

- Near-black window and viewport surfaces with graphite chrome and panels.
- One-pixel pane borders and square docking boundaries.
- Two-pixel radius for interactive fields and buttons; three pixels for transient popups.
- Segoe UI for editor labels and Cascadia Mono for paths and timestamps.
- Muted blue only for selection, focus, and enabled primary actions.
- Green, amber, and red only for backend-published pass, warning, and failure states.
- Static SVG icons; no emoji, font glyph stand-ins, or decorative illustrations.
- No forced transitions, shimmer, animated progress, or ambient motion.

## Workspaces

- `PrepareWorkspace.qml`: policy, physical-system, sensor, recording, compiler, readiness, and output panes.
- `WorldsWorkspace.qml`: world library, render surface, playback timeline, compiler drawer, and world inspector.
- `RunsWorkspace.qml`: durable run table, synchronized evidence surface, timeline, telemetry plots, and run inspector.
- `DiagnoseWorkspace.qml`: failure queue, evidence, counterfactual experiment table, hypotheses, and causal conclusion.
- `TrainWorkspace.qml`: job table, real metric series, structured output, artifacts, and trainer configuration.
- `VerifyWorkspace.qml`: checkpoint table, baseline/candidate comparison, hidden-exam table, regression and promotion gate.
- `CapabilitiesWorkspace.qml`: capability register, Reality Debt history, evidence coverage, and acquisition requirements.

Every workspace uses `SplitView` so the library/outliner, work surface, and inspector remain independently resizable. Vertical splits separate viewports, timelines, evidence tables, graphs, logs, and bottom drawers.

## Reusable components

| Component | Contract |
| --- | --- |
| `DataTable.qml` | Consumes a Qt table model, reuses delegates, emits the activated row, and renders an explicit empty state. |
| `EntityList.qml` | Consumes a Qt list model and provides search/filter UI without inventing records. |
| `LinePlot.qml` | Consumes numeric series; delegates line geometry to `LinePlotItem`; stays empty for fewer than two samples. |
| `ViewportSurface.qml` | Reserves a hardware-rendered surface and viewport tools; remains inactive until a scene service connects. |
| `Timeline.qml` | Provides playback and seek contracts; disabled when no durable run/evidence stream is selected. |
| `Section.qml` / `PropertyRow.qml` | Provide compact collapsible editor forms with layout-safe compound editors. |
| `SelectField.qml` | Provides a bounded, scrollable, keyboard-compatible Qt popup with restrained editor styling. |
| `Panel.qml` / `PanelHeader.qml` / `BottomDrawer.qml` | Provide consistent pane structure without card styling. |
| `SvgIcon.qml` | Loads cached vector resources at display density. |

## Session and backend contracts

`Session.qml` is deliberately small. It retains frontend navigation and selected local URLs, exposes model attachment points, and routes project/recording requests to the application shell. It is not a database or domain service.

The following properties accept service-owned models:

- `projectTreeModel`
- `worldModel`
- `runModel`
- `failureModel`
- `experimentModel`
- `trainingJobModel`
- `checkpointModel`
- `capabilityModel`

Backend integration should replace these `null` values with `QAbstractItemModel` implementations. Roles and columns should remain stable and versioned. Large media, geometry, tensors, and logs should not be copied into JavaScript arrays; expose handles, paged models, or render resources instead.

Long-running services should publish explicit states such as `unavailable`, `ready`, `queued`, `running`, `paused`, `failed`, `cancelled`, and `complete`. The UI must not infer success from the presence of a file, a filled form, elapsed time, or a process log.

## Evidence rules

- A failure points to a durable run and synchronized evidence bundle.
- A causal hypothesis is distinct from an experimentally supported conclusion.
- Counterfactual interventions and their outputs retain provenance.
- Training jobs identify the supported adapter, dataset provenance, configuration, and committed artifacts.
- Hidden-exam records remain separate from generated training experience.
- Promotion requires both generalization and protected regression gates.
- Reality Debt is calculated from versioned evidence, not decorative percentages.
- Missing coverage produces an acquisition requirement, not an invented capture result.

## Rendering and responsiveness

Application startup requests double buffering with swap interval 1. Rendering follows the active display rather than a custom timer; a 120 Hz display can therefore present at the 120 Hz UI ceiling without continuously repainting static panes.

`LinePlotItem` builds a `QSGGeometryNode` only when its series, range, color, or geometry changes. Table views reuse delegates. SVG resources are cached. Workspaces are loaded synchronously to avoid half-rendered transitions, but future heavy datasets and render scenes must be streamed asynchronously through their owning services.

For performance investigations, set `SERVO_QML_LOG` and use Qt's QML profiler, scene-graph diagnostics, and platform GPU tooling. A target ceiling is not a guarantee: actual frame rate depends on the display, render backend, GPU, scene complexity, and service workload.

## Implementation boundary

This frontend does not contain demo simulations, synthetic telemetry, fake training loops, fabricated confidence, or staged pass/fail results. Disabled actions mark service boundaries that still need production implementations. Connecting those services is a separate backend milestone and must preserve the contracts above.
