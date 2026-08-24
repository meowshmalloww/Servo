# Servo frontend contract

Servo's desktop frontend is a Qt 6.11/QML workbench. It provides the production UI shell, persistent media-source registration, a real Vulkan-rendered world viewport, and a native-process reconstruction control surface without fabricating backend results.

## Shell

`Main.qml` owns the menu bar, compact workspace selector, project context, measured performance readouts, settings, global debug drawer, shortcuts, and status strip. Each workflow is loaded as an isolated workspace under `src/ui/workspaces`.

The workspaces are Create World, Worlds, Runs, Diagnose, Train, Verify, Capabilities, and Assistant. They share one global navigation control rather than duplicating a top navigation bar and left activity rail.

## Assistant

`AiChatController` is a native `QAbstractListModel` and asynchronous Qt Network client for Gemini's Interactions API. It accepts text and up to six local images, preserves provider conversation state through `previous_interaction_id`, and exposes only actual provider responses. Set `GOOGLE_API_KEY` or `GEMINI_API_KEY` before starting Servo; without a key the composer stays disabled and explains why. No simulated assistant output is used.

The QML composer owns responsive text entry, attachment previews, model and effort selection, cancellation, and keyboard submission. Network state, payload construction, response parsing, and error handling remain in C++.

## Create World

`MediaSourceModel` is a native, persistent `QAbstractListModel` for the first media-to-world step. It accepts multiple local files, dropped URLs, and recursively selected folders; canonicalizes and deduplicates paths; and references originals without copying them.

- Image registration reads headers through `QImageReader` without decoding full-resolution pixels.
- Video registration runs machine-readable `ffprobe` JSON in one of two bounded background workers.
- The probe records dimensions, average frame rate, duration, frame count when declared, codec/container, pixel format, color metadata, rotation, size, modification time, and a fixed-size sampled SHA-256 identity fingerprint.
- The catalog uses the `servo.media-sources/v1` schema and commits with `QSaveFile`, so a process interruption cannot expose a partially written catalog.
- Restart restores verified metadata and re-probes a source whose size or modification time changed. Missing and invalid sources remain visible with actionable errors.
- Removing an entry removes only its catalog reference; it never deletes the original source.

The model imposes no artificial file-size, duration, resolution, or FPS cap. This does not mean reconstruction has infinite resources: the worker stream-decodes videos, selects bounded keyframes, preflights disk, and checkpoints bounded stages. See [the reconstruction plan](WORLD_RECONSTRUCTION_PLAN.md).

`ReconstructionController` owns the native worker boundary. It discovers the managed Python runtime, performs an exact dependency check including a real gsplat CUDA forward/backward pass, enforces profile disk/VRAM capacity, writes `servo.reconstruction-job/v1` atomically, and launches one detached GPU job. The job survives the UI closing; a durable active-job record and append-only event log support reattachment. The controller validates event schema, worker version, job identity, monotonic sequence, and the published world manifest before exposing success. Build, cancel, retry, resume, and open-folder actions reflect durable worker state rather than QML timers.

## Visual rules

- Near-black viewport, graphite chrome, and one-pixel pane boundaries.
- Small radii only on controls and transient popups; docking surfaces remain square.
- Blue-gray is reserved for focus and selection. Green, amber, and red are semantic states only.
- Static SVG icons; no emoji, glow effects, or ambient animation. Small pixel-grid motion is reserved for active work and can be disabled in Settings.
- All hover, focus, selected, and disabled states preserve text contrast.

## World viewport

`ViewportSurface.qml` contains a real Qt Quick 3D `View3D` in offscreen render mode. It provides:

- a perspective camera and orbit controller;
- orbit, pan, zoom, reset, and camera presets;
- an infinite metric editor grid;
- optional renderer statistics from `QQuick3DRenderStats`;
- a stable scene boundary for future compiled world layers.

Qt Quick 3D renders through Qt's Render Hardware Interface. Servo selects Vulkan before window creation, requests the high-performance adapter on hybrid Windows systems, verifies the actual scene-graph API after initialization, and reports the selected physical device and type. Vulkan initialization failure terminates startup explicitly; there is no OpenGL, WebGL, or Direct3D fallback.

A future Gaussian-splat renderer must be a native C++ QRhi/Vulkan render node attached to this boundary. It must keep culling, sorting, buffers, and draw submission on the native side and must not place millions of splats into JavaScript arrays or QML delegates. CUDA remains the reconstruction compute backend; Vulkan is the desktop and delivery renderer.

Gaussian appearance is not collision geometry. A compiled world must publish independent handles for appearance, metric geometry, physics/collision, actors, sensors, road topology, and uncertainty.

## Data boundary

`Session.qml` contains navigation state and model attachment points. It is not a database or simulation service. `MediaSourceModel` owns the local, versioned source catalog, and `ReconstructionController` owns job-process state. Future service-owned lists and tables should arrive as versioned `QAbstractItemModel` implementations; large media, tensors, point clouds, logs, and geometry should arrive as paged data or native resource handles.

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

1. **Implemented:** pin the isolated native Windows worker; add measured dependency/storage preflight, adaptive keyframes, COLMAP pose gates, gsplat training, complete checkpoints, artifact validation, and durable receipts.
2. Add pose/coverage review and a licensed learned depth/confidence prior for difficult casual footage.
3. Attach a native Vulkan Gaussian-scene provider and independent metric geometry/uncertainty layers to the viewport.
4. Add durable run/evidence models and synchronized playback.
5. Connect causal experiments, training adapters, hidden exams, and promotion gates.
6. Add agent orchestration only after every action has an auditable service contract.
