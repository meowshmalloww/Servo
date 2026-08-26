<p align="center">
  <img src="src/ui/assets/servo-logo.png" width="104" alt="Servo logo">
</p>

<h1 align="center">Servo</h1>

<p align="center">
  <strong>Autonomous CI/CD for physical AI</strong><br>
  Beginning with verified media-to-Gaussian worlds that can be explored in a native Vulkan desktop app.
</p>

## Reconstruction videos

### Yosemite road r9 — latest diagnostic (rejected)

[![Animated HD excerpt of the Servo Yosemite road r9 observed-path audit with RGB, expected depth, and depth-spread panels](docs/assets/reconstruction/yosemite-road-r9-observed-path-audit.gif)](docs/assets/reconstruction/yosemite-road-r9-observed-path-audit.mp4)

<p align="center">
  <strong><a href="docs/assets/reconstruction/yosemite-road-r9-observed-path-audit.mp4">Play the full 24.83-second, 1920 x 360 r9 MP4</a></strong>
</p>

### Gerrard Hall — 100 multi-view photographs

[![Animated HD excerpt of the Servo Gerrard Hall observed-path audit with RGB, expected depth, and depth-spread panels](docs/assets/reconstruction/gerrard-observed-path-audit.gif)](docs/assets/reconstruction/gerrard-observed-path-audit.mp4)

<p align="center">
  <strong><a href="docs/assets/reconstruction/gerrard-observed-path-audit.mp4">Play the full 6.63-second, 1920 x 418 MP4</a></strong>
</p>

The animated previews play directly on the README; selecting either preview opens its higher-resolution H.264 video. The Yosemite r9 clip is a real, hash-bound audit of a serialized diagnostic PLY at 745 registered and between-camera poses. It reached 22.19 dB / 0.707 SSIM on held-out views and 23.04 dB / 0.731 SSIM on registered views, but was rejected: finite-splat sky alpha p95 was 0.975 (release limit 0.10) and minimum path support was 0.572 (release limit 0.90). It is public failure evidence, not a published world, collision geometry, or a photorealism claim. See the [asset notice](docs/assets/reconstruction/README.md) for exact provenance and limits.

<p align="center">
  <img alt="Qt 6.11" src="https://img.shields.io/badge/Qt-6.11-41CD52?logo=qt&logoColor=white">
  <img alt="C++20" src="https://img.shields.io/badge/C%2B%2B-20-00599C?logo=cplusplus&logoColor=white">
  <img alt="Vulkan" src="https://img.shields.io/badge/renderer-Vulkan-AC162C?logo=vulkan&logoColor=white">
  <img alt="Native Windows" src="https://img.shields.io/badge/platform-Windows-0078D4?logo=windows&logoColor=white">
  <img alt="GPLv3" src="https://img.shields.io/badge/license-GPLv3-6A5ACD">
</p>

<p align="center">
  <a href="#what-works-today">What works</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="docs/WORLD_RECONSTRUCTION_PLAN.md">Production plan</a>
</p>

Servo is being built for the [All Things Agentic Hackathon](https://allthingsagentichackathon.devpost.com/). Its long-term goal is a RealityCI agent that observes a robot or vehicle policy, diagnoses failures, creates the missing training experience, evaluates a new checkpoint on hidden scenarios, and promotes or rejects it with evidence.

```text
observe -> diagnose -> create experience -> train -> hidden exam -> promote or reject
```

> [!IMPORTANT]
> The local RealityCI loop is implemented and tested end to end: run, deterministic failure evidence, diagnosis, counterfactual experiments, training, hidden exam, regression protection, promotion, and Reality Debt. Cloud deployment and Gemini diagnosis still require the operator's own Google Cloud credentials. Gaussian appearance worlds remain visual evidence, not collision geometry.

## What works today

| Area | Implemented |
| --- | --- |
| Media ingest | Images, videos, drag-and-drop, recursive folders, source deduplication, bounded metadata probing, and persistent recovery |
| Reconstruction | Native Windows worker with FFmpeg, COLMAP, PyTorch, CUDA, and gsplat; no Docker or WSL |
| Reliability | Source hashing, resource preflight, durable stage receipts, safe cancellation, verified checkpoints, resume, and atomic publication |
| Quality control | Pose gates, held-out appearance checks, exact exported-PLY rerendering, interpolated-path audits, artifact-tail checks, and consecutive-failure rejection |
| World management | Automatic handoff after a successful build, search, sort, rename, storage reporting, safe deletion, and bundle access |
| Exploration | Native QRhi/Vulkan Gaussian rendering, GPU projection and radix sorting, antialiased SH3 splats, HDR composition, a smoothed observed-camera path, and Appearance / inferred Depth / splat Structure / Coverage diagnostics |
| RealityCI | Durable local control API, deterministic scenario runner, real PyTorch checkpoint updates, causal experiments, hidden-seed isolation, regression gates, promotion/rejection, Reality Debt, and connected Qt records |
| Servo Assistant | Gemini and OpenAI chat from local `.env` credentials plus safe in-app commands for opening R17, navigating workspaces, and switching clear/rain/snow visual scenario layers |

Servo does not fabricate progress, quality scores, telemetry, missing surfaces, or agent decisions. A world that misses the configured acceptance gates is rejected instead of being presented as finished.

The diagnostic views are deliberately named by what the artifact proves. Inferred depth is not LiDAR or metres without a scale anchor; splat structure is not a collision mesh; RGB cannot produce a real temperature map. The accepted r6 road remains a visualization/research world, not autonomous-driving ground truth. The required metric road surface, lane/curb/sign topology, uncertainty layer, and dynamic-object tracks are specified in the [world reconstruction plan](docs/WORLD_RECONSTRUCTION_PLAN.md).

## Media to Gaussian world

```text
images / video
      -> color-managed frame selection
      -> camera recovery and sparse geometry
      -> Gaussian optimization
      -> exact-artifact and path validation
      -> verified world bundle
      -> Vulkan Explore
```

1. **Ingest** — Sources are referenced in place. HLG iPhone video is converted through an explicit BT.2020/HLG-to-sRGB path and selected frames are stored as lossless PNGs.
2. **Recover cameras** — Servo compares incremental and calibrated global COLMAP solutions. Bounded Fidelity jobs add guided exhaustive matching, retriangulation, global bundle adjustment, and confidence filtering.
3. **Fit the world** — gsplat supplies the Apache-2.0 CUDA rasterization and densification primitives. Servo owns the training policy, static-confidence masks, geometry losses, resource limits, checkpoint contract, cleanup, and streaming export.
4. **Validate the artifact** — The final `world.ply` is reloaded and rendered at registered and interpolated poses. Appearance, coverage, depth ambiguity, artifacts, and bad temporal sections must pass before publication.
5. **Explore and organize** — Accepted worlds appear in the app's **Worlds** workspace and open in the native Vulkan viewer.

A published bundle includes the Gaussian PLY, cameras, sparse COLMAP data, sanitized source provenance, configuration, appearance parameters, pose/training/audit metrics, validation media, and SHA-256 hashes.

### Free-view quality and robotics truth

A front-facing monocular video cannot observe every surface beside, behind, or inside the scene. Servo does not hide that limit. The next structural revision separates road/curb/sign/sky/dynamic semantics, temporally consistent depth and normals, a surface-constrained road/mesh layer, uncertainty, and generated-content provenance. Renderer popping is a separate Vulkan ordering problem; it does not become correct geometry by sharpening the image.

[NVIDIA ArtiFixer](https://research.nvidia.com/labs/sil/projects/artifixer/) is being evaluated for an optional visual-completion layer because it can generate plausible novel trajectories and distill them back into a representation. It is not integrated into the local worker: NVIDIA's official workflow targets Linux/CUDA and says the lighter 1.3B model fits comfortably on an 80 GB GPU, while this project's tested laptop has 12 GB. Any future generated surface will be labelled `generated` and excluded from collision, road topology, sign truth, and autonomous-planning APIs. The concrete road/sky/floater and free-view milestones are in the [production plan](docs/WORLD_RECONSTRUCTION_PLAN.md#free-view-repair-and-generated-completion-decision).

## Quick start

### Desktop application

After the existing build and Python runtime are present, start the local API and desktop together (no Docker or installation):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-Servo.ps1
```

The launcher reuses an already healthy API, otherwise starts it hidden, waits for `/healthz`, and then opens Servo. The desktop reconnects automatically and restores its last campaign for the same API URL.

Requirements:

- Windows with Vulkan support
- Qt 6.11.1 with Concurrent, GuiPrivate, Quick, Quick 3D, Quick Controls 2, Quick Dialogs 2, SVG, and Test
- CMake, Ninja, and a C++20 compiler
- FFmpeg and ffprobe on `PATH`

```powershell
$env:Path = "C:\Qt\6.11.1\mingw_64\bin;C:\Qt\Tools\mingw1310_64\bin;C:\Qt\Tools\CMake_64\bin;$env:Path"

cmake -S . -B build -G Ninja `
  -DCMAKE_PREFIX_PATH=C:/Qt/6.11.1/mingw_64 `
  -DCMAKE_CXX_COMPILER=C:/Qt/Tools/mingw1310_64/bin/g++.exe
cmake --build build --parallel
.\build\appServo.exe
```

Run the test suites:

```powershell
ctest --test-dir build --output-on-failure
python -m unittest discover -s tests/python -p "test_*.py" -v
```

Servo exits if Qt cannot initialize Vulkan; it does not silently fall back to OpenGL, WebGL, or Direct3D.

### Native reconstruction runtime

The tested lock uses Python 3.11, PyTorch `2.11.0+cu128`, CUDA Toolkit 12.8, COLMAP 4.1.1, gsplat 1.5.3, FFmpeg/ffprobe, and an existing Visual Studio C++ x64 toolchain. The setup does not install or modify Visual Studio.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File tools\reconstruction\setup_native.ps1 `
  -Python "C:\path\to\python.exe"
```

The setup creates a managed per-user environment under `%LOCALAPPDATA%\Servo\reconstruction`, installs the checksum-locked toolchain, and finishes only after real CUDA rasterization and backward-pass probes succeed.

Then open **Create World**, add overlapping images or a mostly static video, choose a profile, and select **Build world**. Successful worlds are added automatically to **Worlds**; select one and choose **Explore**.

For the current hackathon baseline, ask Servo Assistant `open and explore R17`. In Explore, use W/S on the smoothed capture path, A/D for bounded lateral offsets, E/Q vertically, drag to look, and select 1x/3x/6x movement speed. Rain and snow are depthless visual scenario overlays: they never contribute Gaussian support, road geometry, or collision evidence.

## Verified evidence

| Capture | Result | Interpretation |
| --- | --- | --- |
| Yosemite road video · r9 diagnostic | 707,794 cleaned SH3 Gaussians · held-out 22.19 dB / 0.707 · registered 23.04 dB / 0.731 | Rejected: finite sky geometry remains in observed sky and path support falls below the required floor; never shown as a usable world |
| Yosemite road video · Fidelity r6 (historical) | 1,486,817 cleaned SH3 Gaussians · held-out 23.87 dB / 0.791 · exact-PLY registered path 25.25 dB / 0.846 | Stronger observed-corridor visual reference, while close foliage and monocular depth remain limited |
| Gerrard Hall · 100 photographs | 577,553 cleaned SH3 Gaussians · 18.05 dB PSNR · 0.657 SSIM | Coherent engineering benchmark; still below final photorealistic acceptance |
| One-way road video · earlier pipeline | 14.75 dB PSNR · 0.410 SSIM with severe mixed-depth layers | Rejected by the current quality policy; not presented as a usable world |

The video above shows the r9 Yosemite road exact-PLY failure audit. Exact metrics, failure analysis, and remaining reconstruction work are recorded in the [world reconstruction plan](docs/WORLD_RECONSTRUCTION_PLAN.md). The stronger historical r6 and Gerrard Hall audits remain documented in [`docs/assets/reconstruction`](docs/assets/reconstruction/README.md).

## What is Servo's and what is open source?

Servo is its own end-to-end application and reliability layer. It uses established open-source numerical foundations rather than claiming to have invented structure-from-motion or 3D Gaussian Splatting.

| Layer | Source |
| --- | --- |
| Workbench, media policy, training policy, geometry losses, job system, quality gates, export, manifests, world library, and Vulkan viewer | Implemented in this repository · GPLv3 |
| Camera recovery and sparse geometry | [COLMAP](https://github.com/colmap/colmap) / PyCOLMAP 4.1.1 · BSD-3-Clause |
| CUDA Gaussian rasterization and densification primitives | [gsplat](https://github.com/nerfstudio-project/gsplat) 1.5.3 · Apache-2.0 |
| Tensor and media runtime | PyTorch, OpenCV, and an external FFmpeg/ffprobe installation |
| Research basis | [3D Gaussian Splatting](https://repo-sam.inria.fr/fungraph/3d-gaussian-splatting/) paper; the non-commercial Graphdeco source is not bundled or imported |

Pinned versions, hashes, and license identifiers are recorded in [`worker-lock.json`](tools/reconstruction/worker-lock.json).

## Honest limits

- A monocular capture has no absolute metric scale until the user supplies a measurement anchor.
- Servo reconstructs observed evidence; unseen backsides and missing viewpoints are not guaranteed or invented as ground truth.
- An appearance world is not collision-certified geometry for robotics.
- Fast motion, rolling shutter, moving vegetation, reflective surfaces, weak parallax, and incomplete coverage can still make a capture unreconstructable.
- Gemini and OpenAI chat plus deterministic local app actions are connected. Model-authored arbitrary tool execution and cloud-hosted ADK orchestration remain future work.

## Documentation

- [World reconstruction production plan](docs/WORLD_RECONSTRUCTION_PLAN.md)
- [Frontend architecture and contracts](docs/FRONTEND.md)
- [Reconstruction audit asset notice](docs/assets/reconstruction/README.md)
- [Pinned reconstruction runtime](tools/reconstruction/worker-lock.json)

## License

Servo is licensed under [GNU GPL v3.0 only](LICENSE). Qt modules have their own licensing terms; review the [Qt licensing overview](https://doc.qt.io/qt-6/licensing.html) before distributing binaries.
