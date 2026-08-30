# Servo T1 Street Reconstruction Research and Experiment Ledger

**Status:** active T1 reset
**Date:** 2026-08-27
**Servo commit inspected:** `6f1d36c53f9ac2ffcdebed5adf35751881e4ae61` (dirty worktree; experiments must record their own commit and configuration hashes)
**Hard local download limit:** 10 GiB per model or dataset
**Primary target:** normal monocular road video and calibrated/equirectangular 360-degree road video
**Non-target:** object-centric reconstruction and unmeasured collision claims

## Executive decision

Stop the R-series search over small trainer changes. Preserve R17 as the current hackathon visual baseline, retain R35/R36 as diagnostic evidence, and move to T1: a geometry-first street pipeline built from mature open-source components.

T1 separates two products that must not be confused:

1. **Geometry/evidence layer:** poses, intrinsics, confidence-filtered depth, fused point cloud, surfels/TSDF/mesh, road ribbon, semantic vectors, observed/inferred/unknown provenance. Physics, path following, measurements, and future collision work consume this layer.
2. **Appearance layer:** spatially tiled 3D Gaussians, protected road/sign detail, level of detail, visibility support, and a depthless sky/far-field layer. This layer provides photorealism, not collision truth.

The next expensive run is blocked until a short geometry preflight passes. More optimization steps cannot repair a bent camera trajectory, duplicated dynamic objects, or depth layers that only agree from the recorded camera.

## Current evidence

| Artifact | Result | Decision |
|---|---|---|
| R17, 7,000 steps | Exact registered 23.487 dB / 0.776 SSIM; heldout 23.474 dB / 0.771; depth-spread p50 0.114, p95 0.542; 1.456M splats | Preserve as current demo appearance baseline. It is not stable off-path and is not collision-ready. |
| R35, 12,000 steps | Pre-final-fit heldout 21.713 dB / 0.730; road spread p50 0.064, p95 0.150; severe worst-view sky leakage remains | Do not promote without an exact-Ply movement audit; extra training did not beat R17 appearance. |
| R36, Brush 12,000 steps | Brush internal heldout 25.862 dB / 0.771, but Servo exact registered 18.624 dB / 0.522; spread p50 1.506, p95 2.972; anisotropy p99 1583.9 | Rejected as a world. It proves a mature trainer alone does not fix the geometry/input. Keep as calibration evidence. |
| T1-A Horizon geometry -> Servo 3DGS, 1,500 steps | 353,779 Gaussians; heldout 18.894 dB / 0.529; final 20.545 dB / 0.556; depth-spread p50 0.309, p95 0.773 | Rejected. Horizon's coherent depth/pose preflight did not become a high-quality appearance field under the current initializer/trainer. Do not extend this arm. |

R36's spherical-harmonic import was tested: ordinary SH3 beat odd-degree sign flipping and SH0. The mismatch is not an unverified SH convention guess. Brush's own images also contain road/mountain stretching. Do not spend more time trying to promote R36.

## Why the current frame path loses evidence

`servo_worker.py` targets 10 Hz, so the Yosemite source is not sampled at one frame per 60 source frames. Approximately 373 frames were selected from a 44-second, 29.97 fps video. The defect is subtler: the worker skips frames until the next 0.1-second boundary and only then computes focus and overlap. It can therefore keep the first eligible blurry frame and never evaluate a sharper neighboring source frame.

T1 changes this to **decode all source frames, score all candidates, then choose one sharp, exposure-safe, connected frame per time window**. Duplicate adjacent frames are not useful merely because they increase the count. The selected set should normally remain near 8–12 fps, with bridges added only where overlap would otherwise break.

## Target architecture

```text
Perspective video                         360 equirectangular video
        |                                           |
all-frame sharp/overlap selector          calibrated cubemap virtual rig
        |                                           |
        +--------------------+----------------------+
                             |
                   T1 global geometry backbone
              HorizonStream first; WildGS-SLAM A/B
                             |
          poses + intrinsics + depth + confidence + tracks
                             |
             loop closure / pose graph / bundle adjustment
                             |
          depth fusion -> point cloud -> surfels/TSDF/mesh
                             |
             overlapping spatial tiles with shared anchors
                    /                         \
      geometry-constrained 3DGS          road/sign/vector layers
      appearance and LOD                  provenance/uncertainty
                    \                         /
                  Servo viewer, scenarios and agent
                             |
              surface-aware climate simulation
```

For 360 video, the equirectangular source remains the evidence master. Cubemap faces are virtual calibrated cameras with a fixed rig transform and shared timestamp; face seams, exposure, and pole distortion must be audited. A 360 capture does not authorize claiming geometry hidden by occlusion.

## Candidate audit

| Candidate | What it contributes | License / size / machine fit | T1 decision |
|---|---|---|---|
| **HorizonStream** | Long-video poses, intrinsics, depth/confidence, point clouds, loop closure and depth fusion; intended for 10k+ frames with near-constant memory | HF model Apache-2.0, about 4.675 GiB; README reports a low-memory sliding mode around 8.5 GB. Source license must be rechecked before vendoring. | **First geometry backbone.** Run 120-frame preflight, then full selected sequence only if it passes. |
| **WildGS-SLAM** | End-to-end monocular RGB Gaussian SLAM with uncertainty-aware dynamic filtering and no COLMAP pose dependency | Apache-2.0; Linux/older CUDA-oriented environment | **Second independent baseline.** Prepare data now; run in a sealed external environment, not Servo's verified Python runtime. |
| **S3PO-GS** | Outdoor monocular reconstruction from globally scale-consistent pointmaps | MIT repository but MASt3R dependency terms apply; A6000-oriented reference environment | Research A/B after HorizonStream/WildGS; not the first local run. |
| **Scal3R** | Long-video globally consistent geometry with block/global context | About 4.717 GiB; reported ~10.32 GB peak on RTX 4090; model license unclear | Optional quality geometry baseline after license verification; reduce block size/resolution on 12 GB. |
| **Depth Anything 3 Large** | Apache multi-view depth/pose cross-check and local geometry prior | Apache-2.0, about 1.531 GiB | Permissive local depth cross-check. No native Gaussian head is claimed. |
| **DA3 Giant/Nested** | Direct Gaussian output, confidence and richer geometry | About 5.05 GiB; CC-BY-NC-4.0 | Research-only diagnostic, never commercial Servo dependency. |
| **Brush** | Mature Apache trainer and topology calibration | Apache-2.0, native Windows | Keep as external appearance calibration; R36 proves it is not the geometry solution. |
| **2DGS / PGSR / DN-Splatter ideas** | Surface-oriented depth, normals, planar road/sign behavior | gsplat 2DGS path is Apache; several official research repos are noncommercial | Clean-room structural experiments after the global geometry backbone passes. |
| **Street Gaussians** | Static background plus tracked rigid vehicles and driving semantics | Educational/research/nonprofit; assumes richer Waymo/KITTI/LiDAR/tracking inputs | Architecture reference only; do not copy code into commercial Servo. |
| **EDGS** | Dense-correspondence initialization and reduced densification | Noncommercial; still uses COLMAP preprocessing | Research idea only; not a product dependency. |
| **Horizon-GS** | Aerial/ground large-scale unification | A100 80 GB / 100k-step research setting | Not applicable to this one-camera street capture. |
| **RadSplat** | Visibility-guided pruning and faster rendering | NeRF-informed appearance/runtime work | Later compression/runtime study; does not fix poses or road geometry. |
| **Wild3R** | Fast reconstruction from unconstrained sparse photos with transient robustness | A100 reference and feed-forward detail tradeoff | Photo-collection research reference, not the long-video backbone. |
| **InfiniSplat** | Single-image feed-forward Gaussian generation | Apache source; single-image limitation | Not selected for measured street reconstruction. |
| **EasyEnv** | Blender-based single-image visual environment workflow | GPL-3.0+ repository; separate third-party model/renderer terms; downloads approach 10 GiB | Optional visual editing/export concept, not multi-frame measured geometry. |
| **ClimateNeRF** | Surface/semantic-aware flood, snow, smog and wet appearance concepts | MIT; original stack is old Linux/CUDA/PyTorch and NeRF-based | Reimplement the physical layer contracts cleanly over Servo geometry; not a direct runtime drop-in. |

### Dataset gate

| Dataset | Approximate size | Decision |
|---|---:|---|
| InteriorGS | 40.8 GiB | **Do not download.** Interior is also outside current focus. |
| dynamic-maps hard-intersection sample | 3.62 GiB, CC-BY-4.0 | Candidate later for semantics/dynamic validation. |
| StreetView360AtoZ | 4.14 GiB, MIT metadata | Candidate for the 360 ingestion/audit path after checking the files and provenance. |

Every model/dataset fetch must first query metadata, sum file sizes, record hashes/licenses, and fail closed above 10 GiB. No automatic install or weight download is allowed from the desktop UI.

## Ordered T1 experiments

### T1-0 — all-frame evidence selection (complete)

- [x] Locate the worker's first-eligible-frame sampling defect.
- [x] Decode and score every source frame.
- [x] Pick the best candidate in each 0.1-second window using regional sharpness, exposure safety, ORB overlap and motion.
- [x] Produce a hash-bound receipt and contact sheet.
- [x] Compare selected-frame focus and connectivity against the current 373-frame set.

**Accepted T1-0 artifact:** `D:\Servo\diagnostics\t1\yosemite-all-frame-selection-v5`

The accepted pass decoded the same HLG source through Servo's HLG-to-sRGB Mobius transform and selected 418 of 1,307 decoded frames. It has zero unconnected windows, no forced bridge frames, a 0.267-second maximum gap, focus p10/p50/p90 of 362.50/487.64/854.51, and overlap p10/p50 of 0.762/0.817. Compared with the R17 set, focus p10 improved from 349.82 and overlap p10/p50 improved from 0.758/0.807. The selected frame IDs and timestamps are immutable in `selection-receipt.json`.

The earlier v3/v4 outputs are rejected diagnostics: v3 used an incomplete color-metadata fallback and forced every window; v4 was too selective and produced only 256 frames with a 0.467-second gap. Neither may be used by T1-A.

Pass:

- no timestamp gaps above 0.4 seconds;
- median accepted overlap at least 0.25 and at least 48 feature matches where measurable;
- p10 regional focus not worse than current selection;
- selected count within 320–520 for the current 44-second source unless a receipt explains a bridge/failure;
- no decoding, timestamp, or color-transform mismatch.

### T1-A — HorizonStream geometry preflight

1. Use a contiguous 120-frame sharp/connected subset at 10 fps.
2. Start at the lowest-memory documented configuration (`sliding-size=1`, CPU output offload, reduced resolution).
3. Export poses, intrinsics, depth, confidence, raw/global/fused point clouds and runtime/VRAM receipts.
4. Do **not** train Gaussians yet.

Pass:

- all requested frames receive finite poses/intrinsics;
- no camera inversion or discontinuity;
- adjacent translation/rotation jerk has no unexplained p99 spike over 5x median;
- depth is temporally consistent after pose warping on rigid high-confidence pixels;
- fused road evidence does not form duplicated floating layers;
- peak allocated VRAM stays below 11 GiB.

Only after this passes: run the complete selected Yosemite sequence. If it fails, record the blocker and move to WildGS-SLAM instead of tuning blindly.

**120-frame result (automatic geometry gate passed; visual review still required):**

- External source commit: `9602f530d605b465a96b2be88f9e46e5dc9d5c29`.
- Source repository has no root license file; the Hugging Face model card declares Apache-2.0. Do not vendor or redistribute until the source license is resolved.
- Checkpoint: 4,844,138,369 bytes, SHA-256 `734c91d4edb357882735fc046637d82c63cf19fcdda2ce54ab2d5d14b678316b`.
- Native-Windows runtime required isolated `flash-linear-attention 0.5.2`, `fla-core 0.5.2`, `pypose 0.7.3`, `viser 1.0.21`, and `triton-windows 3.7.1.post27`. Servo's verified Python packages were not replaced.
- The official release had an export blocker: `offline_error` was read without being initialized. The diagnostic checkout contains a one-line semantic fix (`offline_error = None`) and remains a dirty external checkout.
- Three-frame smoke test passed model load, CUDA inference and all requested exports after that fix.
- 120 frames completed in 140.3 seconds. Observed total GPU memory use was about 8.37 GiB, below the 11 GiB gate.
- Output: `D:\Servo\diagnostics\t1\horizonstream-yosemite-t1a-run-120\yosemite_t1a_120`.
- Audit: `D:\Servo\diagnostics\t1\horizonstream-yosemite-t1a-run-120\geometry-audit-v2.json`.
- Preview: `D:\Servo\diagnostics\t1\horizonstream-yosemite-t1a-run-120\geometry-preview.png`.
- 120/120 finite poses; rotation determinant error max `8.55e-8`; translation-step p99/median `1.605`; maximum rotation step `0.584 degrees`.
- 120/120 finite positive depth/confidence maps. On 105,669 high-confidence adjacent reprojections, log-depth error p50/p95 was `0.0195 / 0.0856`; 95.94% were within 10% relative depth.
- Point cloud: 5,835,859 finite points, 87,538,066-byte PLY.

This passes the predefined automatic preflight. It does **not** yet prove the road is a single collision-safe surface. The visual point preview is corridor-coherent but still needs road-specific slicing, ground/ribbon fitting, and floating-layer tests before the full 418-frame run or appearance training.

### T1-B — WildGS-SLAM independent baseline

- Use the same frame IDs at 640x360 first, then at the highest resolution that remains below 11 GiB.
- Let WildGS estimate its own trajectory; do not seed it with COLMAP during the diagnostic.
- Export trajectory, Gaussian map, uncertainty/dynamic masks and timing.
- Audit in Servo after a coordinate/PLY adapter with source-view parity tests.

Pass: better modest-motion stability than R17 without losing more than 0.2 dB registered appearance, no screen-spanning road sheets, and no trajectory discontinuity.

**Native-Windows preflight (2026-08-27): blocked, not run.** The recursive
Apache-2.0 checkout is complete at commit
`be187eabbe6862cef3cfe87031ee2e64ad8c4cec`, including lietorch, the
pose-aware Graphdeco rasterizer, and simple-knn. The official stack pins
Python 3.10, PyTorch 2.1.0, CUDA 11.8, xFormers 0.0.22, MMCV and a DROID
checkpoint. Servo uses Python 3.11, PyTorch 2.11.0 and CUDA 12.8. An isolated
no-install compile probe reached `simple-knn` but failed in CUDA C++ headers
with an ambiguous `std` symbol under MSVC 14.50. No Servo packages were
changed and no model weight was downloaded. A fair WildGS run therefore
requires a separate pinned runtime; it is not a same-day drop-in to the
verified desktop process.

### T1-C — optional geometry cross-checks

- DA3-Large: local overlapping windows, depth/pose/confidence only.
- Scal3R: only after license verification and a 120-frame memory preflight.
- S3PO-GS: research-only baseline after dependency/license recording.

Generated or relative-depth results remain inferred and nonmetric.

### T1-D — common fused geometry skeleton

- Align accepted geometry windows to the global trajectory.
- Fuse only high-confidence rigid pixels.
- Separate road/curb/sign/dynamic/sky semantics before fusion.
- Produce point cloud, surfel map, TSDF/mesh, road ribbon and per-cell uncertainty.
- Explicitly mark observed, inferred, generated, ambiguous and unknown cells.

No appearance training begins until the road layer has no duplicated surface inside the observed corridor and the movement audit finds no floating collision candidates.

### T1-E — tiled appearance

- Partition the corridor into overlapping spatial tiles with shared anchor cameras.
- Initialize appearance Gaussians from the accepted geometry skeleton.
- Protect road markings, boundaries and sign planes from aggressive LOD/pruning.
- Keep weak-parallax mountain/sky content in a depthless or directional far-field representation.
- Compare Servo gsplat and Brush on identical poses/geometry; training method is a replaceable appearance component.

### T1-360 — 360-degree ingestion

- Detect/require equirectangular projection metadata or explicit user selection.
- Generate six calibrated cubemap faces per timestamp with fixed rotations and shared optical center.
- Select timestamps before face generation to avoid sixfold duplicate work.
- Audit seam consistency, poles, rig transforms and exposure.
- Run the same T1 geometry/evidence/appearance stages.

**Preparation implementation complete.**
`tools/reconstruction/servo_prepare_360_capture.py` now converts a real 2:1
equirectangular image sequence to six 90-degree PINHOLE cameras with fixed
OpenCV-frame rotations and one shared optical center. It preserves the source
panorama as the evidence master, writes SHA-256-bound derived images and a rig
receipt, rejects non-2:1 inputs and refuses overwrite. T1 video ingestion now
automatically performs this conversion after selecting timestamps when
`--capture-type equirectangular360` is used. Five projection/receipt tests and
the five existing video-selection tests pass. Pose estimation, seam scoring,
and 360 appearance training remain downstream stages; the UI must not claim a
finished 360 reconstruction merely because ingestion succeeded.

## Climate and weather layer

The current particle/shader weather prototype must not be presented as physical weather or training evidence. Disable it from the final demo until a surface-aware layer exists.

The replacement follows ClimateNeRF's useful separation of scene, semantics, physical entities and light transport, adapted to Servo's explicit geometry:

- **Rain:** volumetric streak/occlusion appearance plus a precipitation rate; road response is separate.
- **Wet road:** water-film thickness, roughness/specular response, puddle eligibility from the road proxy, and drainage/slope provenance.
- **Flood:** a physical water surface intersecting the structural mesh; depth and traversability use the geometry layer, never 3DGS alpha.
- **Snow:** accumulation on upward-facing supported surfaces, semantic exclusions, depth/traction parameters, and separately rendered falling snow.
- **Smog/fog:** participating-medium extinction/scattering with a stated visibility range.

Each climate artifact stores parameters, geometry source hash, weather method/version, generated provenance and whether it changes physics. Inferred/generated weather never becomes observed reconstruction evidence.

**Native visual phase complete (2026-08-27).** The Vulkan Gaussian renderer
now emits accumulated alpha plus expected camera-Z support into a second
attachment. Rain, falling/accumulating snow, Beer-Lambert fog, wet-road
response, and a flood preview are composed from finite Gaussian depth/support
instead of a flat QML overlay. The Worlds UI exposes a live intensity control
that adjusts precipitation/accumulation, fog extinction, wet response and
flood coverage; flood is also wired through Servo Assistant. All ten native
CTest targets pass. These controls are
generated appearance previews: flood depth, traction, accumulation mass, and
collision behavior still require the road/structural proxy described above,
and diagnostic view modes disable weather so it cannot conceal gaps.

## Reference-video and method findings

- The inspected Tokyo Alley clip identifies a 5K GoPro capture from multiple
  angles, Luma AI processing, and Unreal Engine presentation. Its camera stays
  mainly inside a narrow, well-observed alley; fuzzy boundary geometry is still
  visible in extracted frames. This is not equivalent to one forward road
  pass.
- The inspected 4K driving-simulation metadata states that four front Canon R8
  cameras at 70 fps and an RTX 5090 were used. Multiple synchronized cameras
  add angular support that Servo's one camera does not have.
- The 500 m showcase is described as a photogrammetry/RealityCapture pipeline,
  not a single-video Gaussian-only reconstruction. Blender or Unreal can edit,
  light, composite, simulate and present reconstructed assets, but they do not
  create missing calibrated observations. Servo should export to them later
  rather than embed either engine into the Qt/Vulkan desktop app now.
- SGD improves sparse street novel views by fine-tuning diffusion with adjacent
  frames and LiDAR depth, then regularizing perturbed 3DGS views. It is a
  diffusion-plus-multimodal supervision method, not a publicly released
  one-video drop-in and not measured geometry in unseen regions.
- Street Gaussians obtains its result from Waymo-style LiDAR depth, tracked
  actors, sky masks, and static/dynamic scene decomposition. Its custom-data
  path remains TODO and its code license is research/nonprofit, so Servo will
  clean-room the architecture rather than copy that repository into a
  commercial-capable build.
- SparseStreet is a scene-graph-aware learnable masking and pruning method for
  an already strong street reconstruction. It reduces storage/render cost but
  does not repair poses, add missing observations, or densify an underfit map.
  Applying it to T1-A would make the quality blocker worse.

## What qualifies as a hackathon pass

The demo may claim a visually driveable observed corridor with an inferred, nonmetric road proxy. It must show forward/reverse travel, a modest lane-scale lateral shift, small yaw/pitch, coverage/uncertainty, semantic road/sign layers, actual render timing, and surface-aware climate controls.

It may not claim measured 360 coverage from a front video, LiDAR, metric scale, validated free space, or collision readiness. Large side/rear turns outside observed evidence should show unknown/inferred environment rather than false fiberglass geometry.

## Experiment receipt requirements

Every run records:

- experiment ID and parent artifact;
- Git commit plus dirty-tree patch hash;
- canonical configuration hash and random seed;
- source/video hash and exact selected frame IDs/timestamps;
- executable/model/repository commit and license;
- model/dataset file sizes and SHA-256 hashes;
- Python/PyTorch/CUDA/driver/GPU and peak memory;
- stage timing, output sizes and cancellation state;
- exact camera/geometry/appearance audit paths;
- accepted/rejected decision with the predefined reason.

Output directories must be new and empty. No cross-arm resume, silent overwrite, or automatic promotion.

## Primary sources

- [HorizonStream repository](https://github.com/3DAgentWorld/HorizonStream) and [Hugging Face model](https://huggingface.co/NicolasCC/HorizonStream)
- [WildGS-SLAM](https://github.com/GradientSpaces/WildGS-SLAM)
- [S3PO-GS](https://github.com/3DAgentWorld/S3PO-GS)
- [Scal3R](https://arxiv.org/abs/2604.08542) and [Hugging Face checkpoint](https://huggingface.co/xbillowy/Scal3R)
- [Depth Anything 3](https://github.com/ByteDance-Seed/Depth-Anything-3), [DA3 Large](https://huggingface.co/depth-anything/DA3-LARGE-1.1), and [DA3 Giant](https://huggingface.co/depth-anything/DA3-GIANT-1.1)
- [Street Gaussians](https://github.com/zju3dv/street_gaussians) and [paper](https://arxiv.org/abs/2401.01339)
- [EDGS](https://github.com/CompVis/EDGS)
- [EasyEnv](https://github.com/TimChen1383/EasyEnv)
- [ClimateNeRF](https://climatenerf.github.io/) and [code](https://github.com/y-u-a-n-l-i/Climate_NeRF)
- [RadSplat](https://m-niemeyer.github.io/radsplat/)
- [Horizon-GS](https://city-super.github.io/horizon-gs/)
- [Wild3R](https://arxiv.org/abs/2606.11894)
- [Leveraging NeRF-rendered Images for 3DGS](https://arxiv.org/abs/2606.09034)
- [Streetscapes](https://arxiv.org/abs/2407.13759)
- [Sat3DGen](https://arxiv.org/abs/2605.14984)
- [InfiniSplat](https://zju3dv.github.io/InfiniSplat/)

## Next checkpoint

Keep R17 as the demo world. Do not extend rejected T1-A or start another
ordinary long optimization. The next reconstruction-quality checkpoint is a
separate pinned WildGS runtime only if it can be assembled without changing
Servo's verified environment, followed by a 120-frame output/parity audit.
In parallel, finish the independent road ribbon and surface-aware weather
physics so car/scenario work is no longer blocked by appearance-Gaussian
geometry.

## T4/T5 tiled-route result — 2026-08-28

The destructive single-PLY merge was rejected. Servo now preserves local
Gaussian fields and publishes them as an explicit route bundle.

- **T4:** five overlapping 96-camera Brush fields, 24-camera overlap, 3,000
  steps each. The complete route passed 10/12 visual checks (83.33%); both
  failed checks were rendered depth-layer spread, so collision remains false.
- **T5:** the same five fields were trained independently for 7,000 steps with
  a higher-density MCMC schedule. The center field improved from 26.176 dB /
  0.761 SSIM to 28.287 dB / 0.871 SSIM. The all-T5 route improved appearance
  but failed the protected support gate in the final route segment.
- **Accepted hybrid:** T5 fields 0–2 plus the broader-support T4 fields 3–4.
  It passes 10/12 checks (83.33%), with 24.318 dB minimum registered-view PSNR,
  23.483 dB p10, 0.798 mean SSIM, 0.906 minimum observed support, and protected
  modest-motion support. Depth-layer checks still fail; the bundle is visual
  appearance only and is not collision validated.

Artifacts:

- `D:\Servo\diagnostics\t5\t5-hybrid-route-validation-v1.json`
- `D:\Servo\runtime\reconstruction\jobs\yosemite-t5-hybrid-full-route-v1-20260828`

The desktop world library exposes the bundle's five independently fitted route
fields with explicit previous/next controls. This avoids pretending an unsafe
parameter merge is a continuous reconstruction. Seamless dual-field prefetch
and cross-fading remain a later renderer task.

## T5 all-route v2 and fiberglass decision — 2026-08-28

The prior hybrid is no longer the selected review world. The new v2 bundle
uses the original high-detail T5 field for all five route segments and stores
each field's matching `cameras.json` beside its PLY. The viewer maps local path
progress to the 373-camera global route and hands off inside the 24-camera
overlap instead of resetting at field boundaries.

Selected review world:

- `D:\Servo\runtime\reconstruction\jobs\yosemite-t5-all-full-route-review-v2-20260828`

Fiberglass forensics found extreme covariance anisotropy in every field. A
128x axis cap preserved every Gaussian and improved the worst depth-spread
statistics, but the full route regressed from 8/12 to 5/12 checks and was
therefore rejected. The capped PLYs remain diagnostics only; original T5 is
unchanged. NVIDIA ArtiFixer source is pinned externally at commit
`a392c4dfe17459ef9952407accdb9fcdcdddba98`, but its official light workflow is
documented for an 80 GB GPU and is not claimed to have run on Servo's 12 GB
Windows machine.
