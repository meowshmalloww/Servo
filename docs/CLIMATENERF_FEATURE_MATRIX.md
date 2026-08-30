# ClimateNeRF feature matrix

Audit date: 2026-08-28. Local source receipt: `sha256:2add8339d002e6bfd6a427e92ad59c4b9a8f83b7c67aee80ec936019c019d089` (87 relevant files). The ZIP is content-identical after CRLF normalization to official `main` commit `3a3e04ae58578983a51dd30c5650c1d61f4b9b22` (91/91 files; no additions or omissions).

Status language is deliberately strict: **located** means source was audited, not that it runs in Servo. **Implemented/tested** applies only to the named boundary.

| Capability | Original source | Servo status | Test/evidence or precise blocker |
|---|---|---|---|
| Hash-grid NeRF; density/RGB; separate geometry/appearance; appearance embeddings | `models/networks.py` | Official reference backend executes in an isolated GPU container | One-step qualification and checkpoint save passed; output quality failed |
| Semantic logits, predicted normals, raw/rendered depth, points, opacity | `models/networks.py`, `models/rendering.py`, `render.py` | Located; adapter schemas preserve evidence provenance | Reference model cannot load |
| Distortion, opacity, sky, semantic, normal, depth and transient-mask losses | `losses.py`, `train.py` | Located; unsupported | CUDA extension/API port not completed |
| Skybox and bounded ray marching | `models/rendering.py`, `models/custom_functions.py` | Located; unsupported | `vren` absent |
| Registered, interpolated, panorama, supersampled and chunked rendering | `render.py`, `render_panorama.py` | Reference chunked renderer executes | 47 T5 held-out RGB/depth pairs produced; quality rejected |
| COLMAP and KITTI-360 datasets | `datasets/colmap.py`, `datasets/kitti360.py` | Fail-closed Servo COLMAP adapter implemented | T5 qualification registered 373/373 images and 77,329 sparse points; scale remains relative |
| Camera convention/round-trip and train/validation/test receipts | dataset modules | Strict dataset manifest and camera transform implemented | CPU contract tests pass; real export correctly rejected |
| Semantic-region PhotoWCT stylization and student model | `datasets/stylize_tools/**`, `stylize.py` | Located; unsupported | bundled 31.9 MiB weight is unaudited; `mmseg/mmcv/cupy/pynvrtc` absent |
| Geometry freeze/drift and multi-view style audit | `stylize.py` plus Servo requirement | Contract only | no stylized checkpoint; not claimed implemented |
| Smog Beer-Lambert transmission, color, bounds, optical-depth cap | `simulate.py` | Reference renderer executes; math tests pass | one-step render is opaque beige and quality-rejected |
| Smog relative/metric units and foreground/background behavior | paper/`simulate.py` | Implemented in contracts/math | selected world is relative scale only |
| Flood plane, intersection and water mask | `simulate.py`, `utility/fit_plane.py` | Numerical primitive implemented/tested | no validated ground plane in local world |
| Dielectric Fresnel, refraction and total internal reflection | `simulate.py` | Independently implemented/tested | normal, grazing and TIR tests pass |
| Water color/clarity/glossy spherical-Gaussian response | `simulate.py` | Located; unsupported end-to-end | no reference scene/depth render |
| FFT/TMA dynamic waves, seed, wind and explicit time | `simulate_wave.py`, `utility/test_dynamic.py` | Deterministic FFT spectral normal generator implemented/tested | not yet a QRhi compute pass; no native parity claim |
| Panorama/environment reflection fallback, guided filtering and AA | `simulate.py` | Located; unsupported | no licensed/selected panorama and reference model unavailable |
| Snow ground/up estimate, candidates and snowfall direction | `make_snow.py`, `utility/cal_vertical.py` | Candidate confidence implemented/tested | no validated normal/ground evidence |
| Snow metaballs, radii, Parzen density and thickness | `models/mb_networks.py`, `make_snow.py` | Metaball kernel implemented/tested | full learned snow checkpoint unsupported |
| Snow visibility/occlusion, sheltered protection and sky exclusion | `models/mb_networks.py` | Placement contract implemented/tested | `torch_scatter`, scene normals and snow network absent |
| Snow illumination, high albedo, scattering and MTMT shadows | `make_snow.py`, `datasets/shadow_tools/**` | Located; unsupported | MTMT weights absent/unaudited |
| Clear/smog/flood/snow/stylized render products, masks and sweeps | render/simulation scripts | Smog execution qualified only | no quality-accepted model; flood plane and snow components absent |
| Immutable derived climate world | Servo requirement | Publisher/verifier implemented/tested | rejects overwrite/tampering; no valid bundle published |
| Detached job states, logs, measured counts, cancel/reattach | Servo requirement | Implemented/tested | process launcher/UI controller not yet implemented |
| Windows runtime and GPU forward/backward qualification | Servo requirement | Implemented/tested through a Windows-hosted Linux GPU container | RTX 4080, CUDA 11.3, PyTorch 1.11, `tinycudann`, `vren`, and `torch_scatter` qualified |
| ClimateNeRF Native smog/water/snow | Servo requirement | Unsupported | fake shader path deleted; no QRhi reflection/compute/snow layer |
| Baked stylized Gaussian | Servo requirement | Unsupported | no stylized training views/checkpoint |
| Worlds UI and derived grouping | Servo requirement | Fail-closed | selector is locked to Clear until a verified quality-accepted bundle exists |
| RealityCI weather-condition descriptor | Servo requirement | Implemented/tested | visual and physical weather are separate; CARLA RGB is rejected as climate source |
| CARLA policy-camera climate synchronization | Servo requirement | Contract value support only | no climate bundle/frame source exists; no fallback allowed |

No rain capability is attributed to ClimateNeRF. Servo's former rain, wet, fog, snow, and flood presentation-shader modes were removed.
