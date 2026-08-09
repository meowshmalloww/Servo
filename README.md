<p align="center">
  <img src="src/ui/icons/app.svg" width="82" alt="Servo logo">
</p>

<h1 align="center">Servo</h1>

<p align="center">
  <strong>Simulation Environment for Robotic Validation and Optimization</strong><br>
  An evidence-driven workbench for finding and closing capability gaps in physical-AI policies.
</p>

<p align="center">
  <img alt="Qt 6.11" src="https://img.shields.io/badge/Qt-6.11-202326?logo=qt&logoColor=white">
  <img alt="C++20" src="https://img.shields.io/badge/C%2B%2B-20-202326?logo=cplusplus&logoColor=white">
  <img alt="GPLv3" src="https://img.shields.io/badge/license-GPLv3-202326">
</p>

Servo is being built for the [All Things Agentic Hackathon](https://allthingsagentichackathon.devpost.com/) **Taskmaster** track. Its product loop is:

```text
record -> compile world -> run policy -> preserve evidence -> diagnose causally
       -> generate targeted experience -> train -> verify -> promote or reject
```

Gaussian reconstruction supplies appearance. Metric geometry, physics, actors, sensors, interventions, and evidence remain separate systems so a convincing image is never mistaken for a valid simulation.

## Current foundation

- Compact Qt/QML desktop workbench with resizable library, viewport, inspector, and debug surfaces.
- Real Qt Quick 3D `View3D` using Qt's Render Hardware Interface; camera orbit, pan, zoom, presets, grid, and renderer statistics are functional.
- Live process FPS activity, CPU, RAM, and graphics-backend readouts—no fabricated telemetry.
- Neutral empty states and disabled service actions until real models and backend services are attached.
- Consistent SVG icon system, high-contrast menus, persistent layout settings, and no forced animation loop.

The simulation, causal-analysis, training, verification, storage, and agent services are intentionally not implemented in this frontend milestone. See [the frontend contract](docs/FRONTEND.md) for integration boundaries.

## Stack

| Layer | Technology |
| --- | --- |
| Desktop shell | Qt 6.11, QML, Qt Quick Controls |
| World viewport | Qt Quick 3D / RHI; Vulkan-capable backend |
| Performance-critical code | C++20; custom Vulkan/CUDA rendering adapters later |
| Model and agent workers | Python, PyTorch, and typed service APIs later |

## Build

Requirements: Qt 6.11 with Quick, Quick 3D, Quick Controls 2, Quick Dialogs 2, and SVG; CMake; Ninja; and a C++20 compiler.

```powershell
$env:Path = "C:\Qt\6.11.1\mingw_64\bin;C:\Qt\Tools\mingw1310_64\bin;C:\Qt\Tools\CMake_64\bin;$env:Path"

cmake -S . -B build -G Ninja `
  -DCMAKE_PREFIX_PATH=C:/Qt/6.11.1/mingw_64 `
  -DCMAKE_CXX_COMPILER=C:/Qt/Tools/mingw1310_64/bin/g++.exe
cmake --build build --parallel
./build/appServo.exe
```

Set `SERVO_QML_LOG` to a writable file path when collecting Qt/QML runtime diagnostics.

## License

Servo is licensed under [GNU GPL v3.0 only](LICENSE). Qt is dual-licensed and individual modules have different open-source terms; Qt Quick 3D is offered under commercial or GPLv3 terms. This repository therefore uses GPLv3 and does not claim that the free Qt edition removes redistribution obligations. Review Qt's [licensing overview](https://doc.qt.io/qt-6/licensing.html) before distributing binaries.
