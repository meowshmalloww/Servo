# Servo frontend contract

Servo's desktop frontend is a Qt 6.11/QML workbench. This milestone establishes the production UI shell and a real hardware-rendered world viewport without fabricating backend results.

## Shell

`Main.qml` owns the menu bar, compact workspace selector, project context, measured performance readouts, settings, global debug drawer, shortcuts, and status strip. Each workflow is loaded as an isolated workspace under `src/ui/workspaces`.

The workspaces are Prepare, Worlds, Runs, Diagnose, Train, Verify, and Capabilities. They share one global navigation control rather than duplicating a top navigation bar and left activity rail.

## Visual rules

- Near-black viewport, graphite chrome, and one-pixel pane boundaries.
- Small radii only on controls and transient popups; docking surfaces remain square.
- Blue-gray is reserved for focus and selection. Green, amber, and red are semantic states only.
- Static SVG icons; no emoji, decorative dots, glow effects, or ambient animation.
- All hover, focus, selected, and disabled states preserve text contrast.

## World viewport

`ViewportSurface.qml` contains a real Qt Quick 3D `View3D` in offscreen render mode. It provides:

- a perspective camera and orbit controller;
- orbit, pan, zoom, reset, and camera presets;
- an infinite metric editor grid;
- optional renderer statistics from `QQuick3DRenderStats`;
- a stable scene boundary for future compiled world layers.

Qt Quick 3D renders through Qt's Render Hardware Interface. The active backend is selected by Qt before window creation and reported in the UI. A future Gaussian-splat renderer should be a C++ rendering component that attaches to this boundary; it must not place millions of splats into JavaScript arrays or QML delegates.

Gaussian appearance is not collision geometry. A compiled world must publish independent handles for appearance, metric geometry, physics/collision, actors, sensors, road topology, and uncertainty.

## Data boundary

`Session.qml` contains navigation state, selected local URLs, and model attachment points. It is not a database or simulation service. Service-owned lists and tables should arrive as versioned `QAbstractItemModel` implementations; large media, tensors, point clouds, logs, and geometry should arrive as paged data or native resource handles.

The frontend does not synthesize runs, failures, telemetry, causal confidence, training progress, exam results, or Reality Debt. Empty models remain empty. An action remains disabled or absent until its owning service can execute it.

## Performance

- Static panes are event-driven; there is no timer-driven animation loop.
- The world is rendered by the Qt scene graph/RHI, not a QML canvas simulation.
- `LinePlotItem` builds native scene-graph geometry only when its inputs change.
- Table and list views reuse delegates; workspaces avoid invisible overlapping render surfaces.
- `RuntimeMetrics` samples process CPU and resident memory once per second and counts actual window frame swaps.
- Split layouts persist their state and expose wider, visible drag targets.

Use `SERVO_QML_LOG` for runtime warnings and Qt's QML profiler plus platform GPU tools for performance investigations.

## Integration order

1. Define versioned project and world manifest schemas.
2. Attach a native compiled-world scene provider to the viewport.
3. Add durable run/evidence models and synchronized playback.
4. Connect causal experiments, training adapters, hidden exams, and promotion gates.
5. Add agent orchestration only after every action has an auditable service contract.
