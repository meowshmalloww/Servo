# Servo

**Simulation Environment for Robotic Validation and Optimization**

Servo is a desktop workbench for closing capability gaps in physical-AI policies. It is designed to compile real recordings into executable worlds, run a connected policy, preserve synchronized failure evidence, test causal hypotheses with interventions, create targeted experience, train through an explicitly supported adapter, and independently gate candidate checkpoints.

Servo is being developed for the [All Things Agentic Hackathon](https://allthingsagentichackathon.devpost.com/) in the **Taskmaster** track.

> Current status: the Qt/QML frontend foundation and all seven workflow layouts are implemented. Simulation, causal experimentation, training, verification, storage, and cloud services are not connected yet. The interface intentionally shows neutral empty or unavailable states instead of fabricated runs, telemetry, progress, or pass/fail results.

## Workflow

```text
Prepare inputs
  -> Compile executable world
  -> Run policy and preserve evidence
  -> Detect and causally diagnose failure
  -> Generate targeted experience
  -> Train through a supported adapter
  -> Run hidden exam and regression gates
  -> Promote or reject checkpoint
  -> Update Reality Debt and acquisition requirements
  -> Repeat
```

Gaussian reconstruction is one appearance source, not the complete simulator. Metric geometry and deterministic physics remain responsible for collision, dynamics, controllable actors, and repeatable interventions.

## Desktop workspaces

| Workspace | Responsibility |
| --- | --- |
| Prepare | Configure the policy adapter, physical system, sensor rig, recording source, and world compiler. |
| Worlds | Inspect compiled appearance, geometry, actors, road graph, sensors, and uncertainty. |
| Runs | Execute and inspect durable policy runs with synchronized frames, telemetry, outputs, and trajectories. |
| Diagnose | Review failure evidence, ranked hypotheses, counterfactual experiments, and supported causal conclusions. |
| Train | Configure a supported training interface and inspect real jobs, objective series, logs, and committed artifacts. |
| Verify | Compare checkpoints using hidden exams, protected regression sets, and an auditable promotion decision. |
| Capabilities | Track evidence-backed Reality Debt and turn missing coverage into precise acquisition requirements. |

The shell uses one top-level workspace navigation bar. Editor panes use compact split layouts, square pane boundaries, contextual two-pixel control corners, SVG icons, and a neutral graphite palette. Blue is limited to focus and selection; green, amber, and red are reserved for real semantic states.

## Honest integration boundary

The frontend accepts Qt item models and service-published series; it does not synthesize operational data.

- Lists and tables remain empty until a real `QAbstractItemModel` is connected.
- Viewports remain inactive until a world or evidence service publishes a render scene.
- Graphs remain empty until a job publishes numeric samples.
- Run, build, experiment, training, exam, promotion, and acquisition actions stay disabled until their owning service is available.
- A root cause is not presented until interventions support it.
- Servo can infer and evaluate arbitrary policies through adapters. Training is available only when the policy exposes a supported training interface.

See [docs/FRONTEND.md](docs/FRONTEND.md) for component and backend contracts.

## Performance model

- Qt Quick scene-graph rendering with display synchronization; no forced redraw timer or decorative animation loop.
- A 120 Hz display can present up to the configured 120 Hz UI ceiling while static panes remain event-driven.
- Reusable table delegates and Qt model/view contracts are used for large record sets.
- Metric series use a C++ `QQuickItem`/`QSGGeometryNode` renderer instead of a JavaScript canvas loop.
- SVG assets are cached and shared through the QML resource module.

This establishes the frontend performance path; real-world frame rate still depends on the renderer, scene complexity, GPU, drivers, and connected services.

## Repository layout

```text
.
|-- CMakeLists.txt
|-- src/
|   |-- app/
|   |   `-- main.cpp                 # Application startup, logging, render synchronization
|   `-- ui/
|       |-- Main.qml                 # Menu, top navigation, workspace loader, status bar
|       |-- Theme.qml                # Neutral design tokens
|       |-- Session.qml              # Frontend session and service/model attachment points
|       |-- components/              # Tables, forms, panels, plots, timeline, viewport
|       |-- icons/                   # Static SVG icon system
|       |-- rendering/               # Scene-graph plot implementation
|       `-- workspaces/              # Seven product workspaces
|-- docs/                            # Product sources and frontend architecture
|-- LICENSE                          # GPL-3.0-only text
`-- .gitignore
```

## Build and run

Servo currently requires Qt 6.11 with Qt Quick, Qt Quick Controls 2, Qt Quick Dialogs 2, and Qt SVG.

```powershell
cmake -S . -B build -G Ninja `
  -DCMAKE_PREFIX_PATH=C:/Qt/6.11.1/mingw_64 `
  -DCMAKE_CXX_COMPILER=C:/Qt/Tools/mingw1310_64/bin/g++.exe
cmake --build build --parallel
./build/appServo.exe
```

Set `SERVO_QML_LOG` to a writable path to retain Qt/QML warnings during runtime QA.

## Qt and open-source licensing

Servo uses Qt 6, QML, and Qt Quick under Qt's open-source licensing terms. Qt is dual-licensed; module obligations differ, and some open-source modules are GPL-only. Servo therefore licenses its own source under **GNU General Public License v3.0 only (`GPL-3.0-only`)**.

Distributors must still audit the exact Qt modules, plugins, tools, examples, and third-party libraries they ship. Refer to Qt's [licensing overview](https://doc.qt.io/qt-6/licensing.html), [open-source obligations](https://www.qt.io/development/open-source-lgpl-obligations), and the [GPLv3 text](https://www.gnu.org/licenses/gpl-3.0.html). This is an engineering note, not legal advice.

The development repository is private during the active hackathon. Authorized reviewers can be granted access for judging.

## License

Servo is licensed under the [GNU General Public License v3.0 only](LICENSE).
