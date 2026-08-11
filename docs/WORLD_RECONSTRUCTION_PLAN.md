# Servo media-to-world production plan

Status: Servo Fidelity 3DGS r6 implemented; a clean monocular-video build passed held-out, exact-PLY, interpolated-path, and native Vulkan acceptance at the preferred appearance tier, 2026-08-11. Metric/collision geometry and arbitrary unseen-view completion remain future work.

This document defines Servo's first product foundation: turn ordinary, unposed images and monocular video into a locally stored 3D Gaussian scene that can later support robotics-world compilation. It deliberately separates what the source media proves from what a generative model may only hypothesize.

## Decision

Build one narrow, auditable pipeline before the agent, training, diagnosis, or simulation features:

```text
source media
  -> durable registration and metadata probe
  -> adaptive keyframes
  -> camera poses, sparse geometry, confidence gates, and scale evidence
  -> incremental Gaussian optimization
  -> validation and artifact cleanup
  -> immutable world publication
  -> native Vulkan viewing
```

The reconstruction worker uses CUDA/PyTorch because the maintained differentiable Gaussian and vision-model ecosystem is CUDA-based. The desktop application and final splat viewer use Vulkan only. Vulkan is not a substitute for PyTorch/CUDA training kernels.

The implemented baseline is native Windows only--no Docker or WSL. It uses a separately versioned Python process, CUDA 12.8, PyTorch 2.11, COLMAP/PyCOLMAP 4.1.1, and a hash-pinned native build of gsplat 1.5.3. Servo owns the media, pose, optimization policy, resource limits, checkpoints, validation, cleanup, and publication contracts; gsplat supplies the Apache-2.0 CUDA rasterizer and `DefaultStrategy` densification/pruning operations. The r6 Fidelity master uses anisotropic 3D Gaussians with degree-three spherical harmonics, antialiased rasterization, AbsGS absolute-gradient detail recovery, explicit HLG/BT.2020-to-sRGB decode, lossless selected frames, static-confidence masks, sparse-depth and mixed-layer penalties, coarse-to-fine full-resolution training, bounded per-frame appearance compensation, and hard Gaussian/VRAM/storage limits. It supports durable hash, extraction, pose, train, validate, audit, and publish receipts; safe checkpoints; held-out PSNR/SSIM; exact exported-PLY rerendering; interpolated-path coverage/depth/appearance gates; streaming PLY validation; detached app-lifecycle-safe execution; cancellation; retry; and resume. The desktop app now includes a native QRhi/Vulkan SH3 renderer with GPU projection/radix sorting and a height-smoothed observed-camera path. Learned dense depth, collision geometry/uncertainty, true visibility compaction/LOD, and hierarchical per-pixel splat ordering remain later milestones.

### 2026-08-11 Fidelity r6 video acceptance

The clean `Yosemite Road - Fidelity r6` run used one 43.6-second 1920 x 1080 iPhone HLG/BT.2020 video on the RTX 4080 Laptop GPU. Explicit color-managed FFmpeg decode and the connectivity-aware sampler retained 373 lossless PNG frames. The required Fidelity pose stage compared incremental and calibrated global seeds under guided exhaustive matching, retriangulation, global bundle adjustment, and confidence filtering. The selected result registered 373/373 frames with 66,716 sparse points, 0.847 px p95 reprojection error, median track length 8, 1.10-degree maximum forward step, 0.277-degree maximum up step, and a 1.374 maximum camera-speed ratio.

Optimization completed all 40,000 steps at source resolution after coarse warmup. It stabilized at 1,975,751 Gaussians and used 3.31 GiB peak allocated / 5.75 GiB peak reserved CUDA memory under the 11 GiB guard. Transactional cleanup removed 488,934 transparent, needle, or oversized candidates and exported 1,486,817 degree-three Gaussians in a 350,890,407-byte binary PLY.

The protected pre-final-fit checkpoint scored 23.87 dB mean PSNR and 0.791 mean SSIM on 47 interleaved unseen frames. The final state scored 24.57 dB / 0.815 across all 373 cameras. After export, Servo reloaded the serialized PLY and rendered a 745-frame path containing every registered camera plus one interpolation between each pair. Exact-PLY registered views scored 25.25 dB / 0.846 on average, with p10 values of 22.22 dB / 0.806 and no consecutive degraded-view run. Alpha support stayed above 93.3% overall, 88.9% in the lower half, and 99.5% in the center. The mixed-depth proxy improved to p50 0.155 and p95 0.698, with 69.6% of supported samples above 10% relative spread. All configured gates passed and the world is labeled `preferred`.

The native Vulkan traversal was tested from 0% to 100% of the smoothed observed path. It stayed upright and continuous with zero camera/sort revision lag, approximately 119.7--119.9 submit Hz, and 3.9--5.5 ms reported whole-frame GPU time on the RTX 4080 Laptop GPU. This is a meaningful correction of the earlier upside-down/stale-sort/approximately-5-FPS failure, not a claim of perfect geometry: close foliage and image borders remain smeared, the depth-spread proxy remains material, unseen surfaces are absent, and the world is not collision-certified.

#### Measured r6 reconstruction cost

The same 43.6-second source provides a concrete local baseline rather than an estimate:

| Measure | Observed value |
| --- | --- |
| Selected evidence | 373 lossless 1909 x 1073 PNG frames from 1,307 decoded video frames |
| Extract | approximately 3 minutes 45 seconds |
| Camera/geometry solve | approximately 42 minutes 47 seconds for the expensive COLMAP solve; the first run then spent extra time in a recovered finalization path |
| Gaussian optimization | 10,890.8 seconds (3 hours 1 minute 31 seconds), 40,000 steps, approximately 3.67 steps/second |
| Clean end-to-end expectation | approximately 3 hours 50 minutes to 4 hours 10 minutes on this laptop for this clip, including final validation and publication; not real time |
| Peak CUDA memory | 3.31 GiB allocated / 5.75 GiB reserved on the 12 GiB RTX 4080 Laptop GPU |
| Recoverable job storage | 13.52 GiB across extraction, pose, checkpoints, audits, and the published bundle |
| Published bundle | 2.39 GiB, including 1.74 GiB of per-camera final validation images |
| Final appearance artifact | 1,486,817 SH3 Gaussians; 350,890,407-byte PLY (334.6 MiB) |
| Checkpoint cost | three retained checkpoints at approximately 1.318 GiB each |

The source-duration ratio is roughly 250x for optimization alone and roughly 320x--345x for a clean full build. Interactive Vulkan rendering is a separate workload: the accepted path ran near the 120 Hz display cadence with 3.9--5.5 ms whole-frame GPU time, but that rendering speed says nothing about reconstruction speed or geometric safety.

### Road-world and autonomy safety contract

The current r6 road is a **no-go for autonomous planning or collision queries**. It is useful for observed-view appearance review and research perception experiments, but it does not yet prove a solid road. The exact exported-PLY audit still reports a 0.698 p95 mixed-depth proxy and 69.6% of supported samples above 10% relative depth spread. Monocular scale is also unknown. A self-driving stack must therefore never infer free space merely because RGB looks plausible.

Servo's road product must publish five separate, traceable layers instead of forcing one Gaussian field to do every job:

1. **Static appearance:** the current SH3 Gaussian field for photorealistic viewing.
2. **Static metric structure:** a confidence-weighted road/curb/sidewalk/sign surface using surfels plus a watertight or explicitly open mesh/TSDF derivative. The road model preserves measured grade and banking while rejecting unsupported floating layers.
3. **Semantic topology:** vector lane boundaries and centerlines, curbs, road edges, crosswalks, stop lines, arrows, sign planes/posts, traffic lights, and their lane relationships. Export an OpenDRIVE/OpenLane-style graph; do not make a planner reverse-engineer topology from RGB.
4. **Evidence and uncertainty:** observed/unobserved space, camera coverage, reprojection confidence, depth variance, semantic confidence, scale provenance, and generated-versus-observed origin at every usable region.
5. **Dynamic actors:** time-indexed object tracks and per-object dynamic Gaussians only for vehicles, pedestrians, cyclists, foliage motion, and temporal appearance. The static road remains a stable 3D layer.

Road signs require targeted evidence fusion, not whole-frame upscaling: detect and segment a sign across frames, select the sharpest calibrated observations, rectify its plane, fuse subpixel detail into a texture atlas, run sign classification/OCR, and require cross-view agreement. The original pixels, pose set, confidence, and any unresolved text remain attached. Generative completion may create a visual hypothesis, but it may not alter the safety map or invent a regulatory sign.

Road surfaces, markings, and curbs require temporally consistent depth and normal priors aligned to SfM, semantic masks, robust piecewise-smooth surface fitting, and explicit vectorization. A metric anchor--stereo/LiDAR, calibrated camera height and odometry, GPS/IMU, or a weaker known dimension--is mandatory before centimetre claims. Planar/surface-aligned Gaussian research such as [2D Gaussian Splatting](https://surfsplatting.github.io/) and [PGSR](https://github.com/zju3dv/PGSR) demonstrates why unconstrained volumetric splats are poor geometry, but their reference implementations have research/noncommercial restrictions and are not copied into Servo. Permissive implementation references include [DN-Splatter](https://github.com/maturk/dn-splatter) for depth/normal supervision, [SplatAD](https://github.com/carlinds/splatad) for camera/LiDAR autonomous-driving rendering, and [Video Depth Anything](https://github.com/DepthAnything/Video-Depth-Anything) Small for Apache-2.0 temporally consistent relative-depth experiments.

The map schema follows established driving representations: [OpenLane-V2](https://github.com/OpenDriveLab/OpenLane-V2/blob/master/docs/features.md) represents 3D lane centerlines, boundaries, pedestrian crossings, traffic elements, and topology; [ASAM OpenDRIVE 1.9.0](https://www.asam.net/standards/detail/opendrive/) carries lane geometry, road marks, signals, elevation, and superelevation. These are structural outputs, not visual filters.

The Vulkan viewer now exposes four honest views from the existing artifact: **Appearance**, **relative inferred Depth**, **splat Structure**, and **opacity Coverage**. Depth is not labelled LiDAR and is not metres without scale. Structure is a splat-axis cue, not a certified normal. Coverage exposes weak evidence instead of hiding it. Future semantic, lane-topology, metric-surface, and sparse-SfM views must be backed by published artifacts. A temperature view is allowed only when a thermal sensor or calibrated thermal reconstruction exists; RGB cannot supply real temperature. A LiDAR view is allowed only for actual LiDAR returns; an RGB-derived point cloud must remain labelled inferred depth or SfM points.

For this product, 4D Gaussian splatting is **not** a replacement for 3D. Keep the road, curb, buildings, poles, and signs in a stable 3D world; add 4D/per-object tracks for moving actors or illumination changes. Methods such as [AutoSplat](https://autosplat.github.io/) and [Street Gaussians](https://github.com/zju3dv/street_gaussians) likewise separate background structure from dynamic foreground. Putting the entire road into a deformable 4D field would make collision geometry time-dependent and harder to validate without fixing the underlying scale and surface problem.

### Free-view repair and generated completion decision

One forward-facing video can support a wider lateral viewing corridor than the exact camera line, but it cannot observe the back of a tree, the far side of a vehicle, a room behind a doorway, or road hidden by an occluder. Servo therefore treats three different failures separately:

1. **Renderer instability:** the geometry exists, but global center-depth sorting makes splats pop or blend differently while the camera rotates. The production Vulkan path requires a clean-room hierarchical tile/per-pixel ordering implementation inspired by [StopThePop](https://github.com/r4dl/StopThePop), plus temporal popping tests. This changes compositing, not geometry.
2. **Bad observed geometry:** floaters, sky splats, doubled road layers, giant needles, or weak depth make an observed region collapse off-axis. This is repaired with semantic masks, temporally consistent depth and normals, surface constraints, multi-view support pruning, and a short post-cleanup refinement. It must pass exact-PLY off-axis sweeps before publication.
3. **Unobserved content:** no image contains the required surface. A generative model may supply a plausible visual hypothesis, but it cannot convert that hypothesis into measured road, collision, sign, or free-space truth.

[NVIDIA ArtiFixer](https://research.nvidia.com/labs/sil/projects/artifixer/) is a strong candidate for the third case. It uses opacity-conditioned video diffusion to generate novel camera trajectories and can distill those pseudo-views back into a 3D representation. NVIDIA describes the result as *plausible* reconstruction in unobserved areas and notes remaining changes near unexplored peripheries. The official repository recommends Linux/CUDA Docker and states that even its 1.3B checkpoint fits comfortably on a single 80 GB GPU for all workflows. Servo will not install Docker, silently offload data, or pretend that this workflow fits the local 12 GB RTX 4080 Laptop. ArtiFixer is therefore an optional future cloud/large-GPU **visual completion** worker, never a dependency of the verified local geometry path.

The next local reconstruction revision is sequenced as follows:

| Priority | Production change | Required evidence |
| --- | --- | --- |
| P0 | Generate temporally consistent relative depth with Apache-2.0 Video Depth Anything Small in bounded windows; align it to reliable SfM tracks and reject low-confidence pixels | Lower road/center depth-spread tails without held-out RGB regression; no metric claim without a scale anchor |
| P0 | Publish semantic masks for road, curb, lane marking, sign, sky, vegetation, dynamic actor, water, and reflection; intersect them with the existing epipolar static-confidence masks | Per-frame mask hashes, temporal consistency metrics, and manual correction support |
| P0 | Fit a robust piecewise-smooth road surface that preserves sustained grade/bank; supervise road splats toward the surface and reject disconnected road components above or below it | Road height residual, slope/bank continuity, lane-width consistency, and zero unsupported floating-road components |
| P0 | Remove sky from finite collision/road geometry and render it as a separate infinite environment layer; do not seed or retain finite sky Gaussians | Finite sky-splat count is zero in the structural artifact; horizon and tree-boundary coverage are reviewed separately |
| P0 | Fuse signs and road markings across sharp calibrated frames using planar rectification and super-resolution from real observations | Cross-view OCR/class agreement and a provenance-linked texture atlas; generated text never enters the map |
| P1 | Add confidence-weighted depth/normal supervision and surface-aligned surfels/mesh extraction following the permissive ideas demonstrated by [DN-Splatter](https://github.com/maturk/dn-splatter) | Mesh/TSDF consistency, uncertainty, and held-out reprojection tests independent of the appearance splat |
| P1 | Replace global splat-center ordering with Vulkan tile binning and hierarchical per-pixel ordering; add visibility compaction and LOD after parity | Continuous-rotation popping metric, gsplat/Vulkan golden renders, visible-count and GPU-time measurements |
| P2 | Generate lateral/interior pseudo-views with ArtiFixer-class models on an explicitly selected large-GPU worker and distill a separate visual layer | Every generated texel/surface is tagged `generated`; observed references remain anchors; no generated layer is accepted by collision or planning APIs |

“Never broken from every camera” is not a valid acceptance statement for finite, one-sided evidence. The production replacement is measurable: a declared camera envelope, semantic per-region tail gates, off-axis/interpolated trajectories, temporal popping scores, a generated-content mask, and an explicit no-go volume. A robot may leave the original camera line only where the structural layer and its uncertainty gate pass; a visually filled region alone never grants permission.

### 2026-08-10 Fidelity acceptance

The clean `gerrard-fidelity-r3` run used 100 unposed full-resolution photographs on the existing RTX 4080 Laptop GPU. Both incremental and calibrated global SfM completed; the gated global solution registered 100/100 images with 50,817 sparse points, 0.668 px mean and 1.416 px p95 reprojection error. Fidelity optimization ran all 40,000 steps, used full resolution for 36,000 of them, stabilized at 609,902 Gaussians after densification, and peaked at 1.664 GiB reserved CUDA memory. Transactional cleanup removed 32,349 transparent or needle candidates and published 577,553 degree-three Gaussians.

The immutable world contains 27 hashed artifacts (198.14 MiB total, including a 129.99 MiB streaming binary PLY), sanitized provenance, cameras and normalization transforms, exact runtime/configuration identity, and all 12 held-out target/render comparisons. Structural and artifact gates passed, but held-out appearance measured 18.05 dB mean PSNR and 0.657 mean SSIM. That clears the deliberately permissive engineering floor, not the preferred 23 dB / 0.75 tier, so the artifact is correctly labeled `review-required`. Visual review finds coherent building geometry and readable architectural detail, with remaining foliage blur/floaters, softened ground, and sky/occlusion-boundary artifacts. This is evidence that the native pipeline is real and durable; it is not evidence that arbitrary media has reached final best-in-class quality.

Servo keeps two independently versioned world products:

1. **Appearance:** 3D Gaussians for photorealistic novel-view rendering.
2. **Geometry:** a mesh/TSDF, scale evidence, uncertainty, and a validated navigation envelope for collision, ray queries, and robotics use.

A visually convincing splat is never treated as metric or collision truth.

## Product truths

- The application accepts source resolution, frame rate, duration, and file size without an artificial UI cap. Processing remains bounded through streaming, keyframes, chunks, levels of detail, disk preflight, and resumable stages.
- An arbitrary monocular video has no guaranteed absolute scale. Dependable centimetre or millimetre accuracy needs at least one scale anchor: a known dimension, marker, measured camera height, calibrated baseline, odometry/IMU, GPS, or later LiDAR.
- An unseen surface cannot be reconstructed as observed fact. Optional completion must be a separate `generated` layer and must not silently enter collision, safety, or metric evaluation.
- A gap-free result is a quality claim only inside the validated observation envelope. Outside it, the viewer must expose uncertainty instead of hiding it.
- Standard 3D Gaussian appearance contains captured lighting. It is not natively a physically correct ray-traced or relightable scene. Relighting and ray queries require recovered geometry, normals, materials, illumination, and explicit validation.
- The first supported capture class is a mostly static scene with useful parallax. Dynamic objects, rolling shutter, severe motion blur, water, sky, mirrors, and exposure shifts require masks or specialized handling.

These constraints follow directly from the problem formulation in [LongSplat](https://openaccess.thecvf.com/content/ICCV2025/html/Lin_LongSplat_Robust_Unposed_3D_Gaussian_Splatting_for_Casual_Long_Videos_ICCV_2025_paper.html), the geometric role of [2D Gaussian Splatting](https://surfsplatting.github.io/), and the inverse-rendering limitations documented by [GS-IR](https://openaccess.thecvf.com/content/CVPR2024/html/Liang_GS-IR_3D_Gaussian_Splatting_for_Inverse_Rendering_CVPR_2024_paper.html).

## Architecture

```mermaid
flowchart LR
    UI["Qt 6.11 desktop"] --> CATALOG["Source catalog + job database"]
    UI --> VK["Native Vulkan viewer"]
    CATALOG --> WORKER["Versioned reconstruction worker"]
    WORKER --> FFMPEG["FFmpeg stream decode"]
    WORKER --> POSE["COLMAP camera poses + sparse geometry"]
    WORKER --> GS["Servo trainer + gsplat CUDA optimization"]
    WORKER --> QA["Held-out quality and geometry gates"]
    QA --> PUBLISH["Atomic world publication"]
    PUBLISH --> VK
    PUBLISH --> APPEARANCE["Splats + LOD"]
    PUBLISH --> GEOMETRY["Mesh/TSDF + uncertainty"]
```

The native application must not import Python, Torch, CUDA, or COLMAP into its process. It launches a separately versioned worker, consumes structured events, and owns durable job state. A worker crash must not take down the UI or corrupt the last verified artifact.

On Windows, the production baseline is a per-user native runtime under `%LOCALAPPDATA%\Servo\reconstruction`. The app launches it as a detached process with an exact compiler/CUDA environment and never imports Python or CUDA in-process. A durable active-job record and append-only event log let the UI close and later reattach without terminating training. The worker writes attempt outputs first, validates and hashes them, then atomically publishes the canonical world directory. The gsplat extension is built during explicit setup rather than during a reconstruction job.

## Stage contracts

Every stage writes an atomic receipt containing input hashes, configuration hash, tool versions, start/end timestamps, outcome, metrics, log path, and artifact hashes. A stage is reusable only when its receipt and every declared artifact validate.

### 1. Register sources

- Reference originals in place; never duplicate a large source merely to add it.
- Persist canonical path, stable asset ID, file size, modification time, sampled content fingerprint, and probe result.
- Use `ffprobe` JSON for video streams, duration, average and nominal frame rate, resolution, codec, pixel/color metadata, rotation, and timestamps.
- Read only image headers during registration.
- Probe in bounded background workers. A corrupt or unsupported file becomes a visible per-item error; it does not abort other imports.
- Recursively scan explicitly selected folders and deduplicate canonical paths.
- Preserve variable-frame-rate presentation timestamps during later extraction.

The metadata boundary follows the machine-readable output supported by [ffprobe](https://ffmpeg.org/ffprobe-all.html).

### 2. Preflight resources

Before creating derived data, record and validate:

- free storage in the worker and publication locations;
- NVIDIA device, driver, CUDA runtime, compute capability, total/free VRAM;
- exact FFmpeg, COLMAP, Python, PyTorch, CUDA, and gsplat versions;
- source readability and fingerprint stability;
- expected temporary-data range and chosen eviction policy.

There is no silent quality degradation. If a lower resolution, smaller Gaussian cap, or shorter optimization window is needed, the selected profile and reason are recorded in the job.

### 3. Plan and extract frames

- Stream-decode; do not expand a whole video to frames up front.
- Preserve source ID, frame index, presentation timestamp, rotation, and decode settings in every frame record.
- Select keyframes using blur, parallax/flow, feature coverage, overlap, scene cuts, and exposure changes. Input FPS is evidence density, not a target training FPS.
- Split or recalibrate when focal length or camera model changes.
- Keep overlapping temporal windows so loop closure and global alignment remain possible.
- Derived frames are evictable and reproducible from the immutable source plus extraction receipt.

### 4. Recover cameras, sparse geometry, and scale evidence

The first stable baseline is COLMAP sequential structure-from-motion with shared intrinsics when the capture supports that assumption. Gate it on registered-frame ratio, connected components, track length, reprojection error, and camera-path sanity before Gaussian training. COLMAP is BSD-licensed and supports ordered and unordered image collections: [COLMAP](https://github.com/colmap/colmap).

For difficult casual footage, add a windowed depth/pose prior rather than replacing geometric verification. The intended 12 GB research path is:

- small overlapping pose/depth windows;
- confidence-aware Sim(3) alignment;
- loop closure and global bundle adjustment;
- learned depth used as a prior, never as unquestioned metric truth.

[Depth Anything 3](https://github.com/ByteDance-Seed/Depth-Anything-3) is the leading candidate for the streaming prior where its selected weight license permits distribution. LongSplat is the closest architectural match for casual long video, but its repository inherits research/noncommercial restrictions and is an architecture reference, not a directly copied product dependency: [LongSplat repository](https://github.com/NVlabs/LongSplat).

### 5. Optimize the Gaussian scene

The worker uses Servo's checkpointable trainer initialized by confidence-filtered COLMAP sparse points and the maintained Apache-2.0 gsplat rasterizer and `DefaultStrategy` operations. Keeping the optimization and artifact policy owned avoids importing Nerfstudio's unrelated server/viewer stack while preserving validated CUDA and densification primitives: [gsplat](https://github.com/nerfstudio-project/gsplat).

The production appearance representation is `servo-fidelity-3dgs-v1`:

- anisotropic 3D Gaussians with degree-three spherical harmonics;
- Mip-Splatting-style antialiased rasterization for stable zoom and resolution changes;
- AbsGS absolute projected gradients with its calibrated growth threshold for finer structure;
- a coarse-to-full-resolution schedule with exact camera-intrinsic scaling;
- bounded per-frame log-gain and color-bias nuisance parameters used only during optimization, while the exported world remains canonical;
- deterministic Gaussian and VRAM limits, transactional checkpoints, cleanup statistics, and a streaming binary PLY fidelity master.

3DGS MCMC remains an experimental policy because its stochastic relocation and growth path needs a separately proven deterministic memory budget on the 12 GB target. 2D Gaussian Splatting is reserved for the independently validated geometry and surface layer; replacing the appearance master with it would mix two different product claims. 3DGUT becomes relevant when Servo retains raw fisheye distortion, rolling shutter, or secondary-ray cameras instead of the current undistorted pinhole training set.

For the RTX 4080 Laptop GPU with 12 GB VRAM:

- batch size one with antialiased rasterization is the production baseline; a profile that consumes the complete 12 GB is not a safe default;
- target a measured training peak at or below the declared profile budget: Balanced is capped at 10.5 GiB and Fidelity at 11.0 GiB;
- use bounded Gaussian growth, scene-relative scale and anisotropy cleanup, and multiresolution training;
- optimize geometry at moderate resolution before tiled/high-resolution appearance refinement;
- keep inactive spatial chunks, source frames, features, and depth maps in RAM or on disk;
- checkpoint the complete trainer state, not only exported splat parameters;
- on CUDA out-of-memory, preserve diagnostics and allow one policy-controlled retry with an explicitly recorded lower resource profile.

Long-video improvement after the stable baseline adopts the transferable parts of LongSplat: incremental pose/scene optimization, visibility-local work sets, depth-aligned initialization, occlusion-aware addition of newly observed regions, periodic global refinement, and adaptive spatial anchors.

### 6. Remove artifacts and validate

Required defenses against floaters, needles, gaps, and view popping:

- dynamic/sky/water/reflection masks;
- robust photometric loss and per-frame exposure/color compensation;
- confidence-weighted depth and reprojection losses;
- scale and anisotropy limits, followed by effective-rank evaluation;
- multi-view depth, normal, visibility, and reprojection consistency;
- low-opacity, low-support, isolated-outlier pruning only after held-out validation;
- antialiased rendering and multiscale tests.

[Mip-Splatting](https://openaccess.thecvf.com/content/CVPR2024/html/Yu_Mip-Splatting_Alias-free_3D_Gaussian_Splatting_CVPR_2024_paper.html) addresses zoom/sampling artifacts. [PUP 3D-GS](https://openaccess.thecvf.com/content/CVPR2025/html/Hanson_PUP_3D-GS_Principled_Uncertainty_Pruning_for_3D_Gaussian_Splatting_CVPR_2025_paper.html) motivates sensitivity-based post-training pruning, while [Compressed 3DGS](https://openaccess.thecvf.com/content/CVPR2024/html/Niedermayr_Compressed_3D_Gaussian_Splatting_for_Accelerated_Novel_View_Synthesis_CVPR_2024_paper.html) motivates a separate compressed delivery artifact. Neither optimization is allowed to replace the fidelity master before quality comparison.

The implemented validation uses held-out temporal blocks or isolated still-image samples and records PSNR, SSIM, visual comparisons for every held-out view, reprojection errors, registered-frame coverage, appearance bounds, Gaussian cleanup and outlier statistics, artifact size, configuration identity, and peak VRAM. LPIPS, depth consistency, system RAM, Vulkan render performance, and a continuous visual sweep through the supported camera envelope remain acceptance extensions.

### 7. Publish and render

A world is published by atomic rename only after:

- its schema and every artifact parse successfully;
- hashes match the stage receipt;
- the fidelity splat renders through Servo's actual Vulkan viewer;
- geometry and uncertainty artifacts load independently;
- the validated camera envelope is present;
- provenance classifies content as `observed`, `interpolated`, or `generated`.

The fidelity master remains available. LOD/pruned/compressed derivatives point back to it and record their measured quality delta.

## Durable job schema

The control-plane contract is a versioned `job.json`, not console text:

```json
{
  "schema": "servo.reconstruction-job/v1",
  "jobId": "uuid",
  "state": "queued|running|paused|failed|cancelled|ready",
  "stage": "probe|extract|pose|depth|optimize|validate|publish",
  "sourceManifest": "sources.json",
  "sourceManifestHash": "sha256:...",
  "configurationHash": "sha256:...",
  "workerLock": "worker-lock.json",
  "completedStageReceipts": [],
  "activeCheckpoint": null,
  "lastKnownGoodCheckpoint": null,
  "metrics": {},
  "artifacts": [],
  "error": null
}
```

Worker events use JSON Lines with schema, job ID, monotonic sequence, timestamp, stage, event type, measured progress when available, and a receipt/artifact reference. The UI never invents a percentage for an operation whose denominator is unknown.

## Vulkan application contract

- Call `QQuickWindow::setGraphicsApi(QSGRendererInterface::Vulkan)` before creating a window.
- Select the discrete Vulkan physical device when available, and record the chosen device.
- Verify the actual scene-graph API after initialization. Vulkan failure is explicit; there is no OpenGL, WebGL, or Direct3D fallback.
- Keep Qt Quick UI and the future splat renderer on the same Vulkan/QRhi device.
- Use Qt's automatic Vulkan pipeline cache and add a versioned application cache after the splat pipelines exist.
- Implement the splat renderer as native C++/QRhi or a native Vulkan render node. Never create millions of QML objects or JavaScript-array splats.
- Add direct CUDA-Vulkan interop only after the file boundary is stable and separately tested. It is not required for the first production slice.

Qt documents the early Vulkan selection and failure behavior in its [scene-graph renderer documentation](https://doc.qt.io/qt-6/qtquick-visualcanvas-scenegraph-renderer.html). `QQuickRhiItem` is the likely future viewport boundary, with the explicit caveat that QRhi private APIs have limited compatibility guarantees: [QQuickRhiItem](https://doc.qt.io/qt-6/qquickrhiitem.html).

## UI and UX required for the first feature

### Source loading

- A large drop target for files and folders.
- Multi-file and recursive folder selection.
- Clear statement that originals stay in place and are not copied on import.
- One row per source with real status: queued, probing, ready, missing, unsupported, or error.
- Resolution, average FPS, duration, codec, size, and full path from the real probe.
- Retry failed probe and remove catalog reference actions. Removal never deletes source media.
- Source count, ready/error count, aggregate original size, and catalog location.
- Visible folder-scan activity with no fake percentage.

### Build setup

- Output/workspace location and free-space estimate.
- Quality/resource profile with its expected VRAM and derived-data range.
- Capture warnings for blur, insufficient parallax, dynamic content, variable intrinsics, and missing scale anchor.
- Real dependency readiness for Vulkan, NVIDIA/CUDA, FFmpeg, COLMAP, and the pinned worker.
- Build, cancel, resume, and retry actions governed by the durable job state.

### Progress and review

- Stage timeline with measured counts and stage receipts.
- Live log links, last checkpoint, resource usage, and failure reason.
- Pose/coverage inspection before expensive optimization.
- Held-out reconstruction metrics and visual compare before publication.
- Uncertainty and observation-envelope overlays in the Vulkan viewer.

## Milestones

### M1 — Native ingest and Vulkan enforcement

- Vulkan-only startup with explicit runtime verification.
- Persistent, in-place image/video source catalog.
- Background image-header/ffprobe metadata and sampled fingerprints.
- Multi-file, folder, and drag/drop UX with real errors and aggregate size.
- Documentation and automated model/probe tests.

Exit gate: a multi-gigabyte video can be registered without copying it or growing app memory with source size; restart restores the catalog; Vulkan is the measured active backend.

### M2 — Reproducible worker and frame planner

- Pinned native Windows worker environment and dependency lock.
- Preflight, storage estimate, streaming decode, adaptive keyframes, timestamps, receipts, cancel/resume.

Exit gate: variable-frame-rate, rotated, 4K/8K, Unicode-path, corrupt, and truncated inputs produce deterministic frames or explicit recoverable errors.

### M3 — Camera and geometry gate

- COLMAP sequential SfM, optional licensed matcher fallback, pose/depth confidence, scale-anchor UI, quality gate, and inspection view.

Exit gate: disconnected or low-quality reconstructions cannot proceed silently; a passing dataset has reproducible cameras and quantitative evidence.

### M4 — Fidelity Gaussian baseline

- Pinned gsplat training, complete checkpoints, bounded 12 GB profiles, held-out evaluation, fidelity PLY, and artifact publication.

Exit gate: crash/restart and OOM recovery pass; the exported splat parses and renders in the actual Vulkan viewer; quality and resource baselines are stored.

### M5 — Casual long-video quality

- Windowed depth/pose priors, loop closure, incremental spatial optimization, visibility-aware additions, artifact controls, and uncertainty.

Exit gate: locked casual-video datasets improve over M4 without violating the 12 GB target or regressing restart correctness.

### M6 — Geometry, LOD, and delivery

- Mesh/TSDF publication, validated robotics envelope, pruning, multiscale LOD, compressed derivative, and streamed Vulkan scene chunks.

Exit gate: collision/ray queries never use generated content; LOD transitions meet visual and frame-time thresholds; every derivative is traceable to the fidelity master.

### Deferred

- 4D/dynamic reconstruction.
- Generative unseen-surface completion.
- Inverse rendering, material editing, and physically based relighting.
- Direct CUDA-Vulkan sharing.
- Cloud execution and storage.

These are separate products or quality layers, not shortcuts around the validated 3D baseline.

## Acceptance matrix

| Area | Required test |
| --- | --- |
| Ingest | Constant/variable FPS, rotation, 4K/8K, long duration, Unicode and long paths, corrupt/truncated files, missing source after restart |
| Persistence | Atomic manifest writes, app kill during save, duplicate import, moved/modified source, schema migration |
| Resources | Disk-full preflight/runtime, peak RAM/VRAM, bounded probe concurrency, CUDA OOM retry policy |
| Reconstruction | Registered-frame ratio, connectivity, reprojection error, held-out PSNR/SSIM/LPIPS, depth consistency |
| Artifacts | Floaters, spikes/needles, holes, popping, zoom aliasing, path outside validated envelope |
| Recovery | Cancel and terminate during every stage, checkpoint corruption, worker restart, idempotent rerun |
| Renderer | Vulkan required, discrete-device record, resize/minimize/device-loss handling, real splat parse/render/hash |
| Release | Dependency lock, checksums, model-weight license, FFmpeg build flags, SBOM, third-party notices |

## Dependency and license policy

Ship only dependencies and weights whose terms fit the intended distribution:

| Candidate | Policy |
| --- | --- |
| Nerfstudio | Apache-2.0; algorithm and interoperability reference, not a runtime dependency |
| gsplat | Apache-2.0; maintained Gaussian CUDA backend |
| COLMAP | BSD-3-Clause; initial SfM backend |
| FFmpeg | Pin a known build/configuration; audit LGPL/GPL/nonfree flags before redistribution |
| LongSplat | Architecture reference unless separately licensed; inherited research/noncommercial terms |
| Original Graphdeco 3DGS | Do not copy into the product under its noncommercial research license |
| 2DGS/PGSR research repos | Evaluate method and exact dependency/weight licenses separately before product use |
| Generative completion models | Separate license, provenance, and safety review; never default robotics truth |

The stable baseline must be version-locked as one tested environment. Newer COLMAP, Nerfstudio, gsplat, Torch, or CUDA components enter through a repeatable benchmark and migration, not an unreviewed package upgrade.
