# ClimateNeRF license audit

Audit date: 2026-08-28. Nothing in this audit grants rights beyond the referenced licenses.

| Component | Source/version | License evidence | Servo use/redistribution decision |
|---|---|---|---|
| ClimateNeRF root source | official commit `3a3e04ae58578983a51dd30c5650c1d61f4b9b22`; local normalized match 91/91 | Root `LICENSE`: MIT, copyright 2022 James Lin | External read-only invocation/reference. Servo's independent equations cite the source; no source copied. |
| `vren` CUDA code | `models/csrc/**` in root; isolated container image `sha256:cf9bb69574cf9ec47e6006c922f99a831dac886122b0ee1636f7b6f391881764` | Covered by root MIT except `helper_math.h`, whose header provenance says NVIDIA CUDA Samples | Built only inside the local qualification image; not redistributed. NVIDIA header terms still require resolution before distribution. |
| tiny-cuda-nn | NVlabs tag `v1.6`, built for CUDA 11.3/sm86 in the isolated image | Upstream dependency; redistribution review remains separate from this runtime qualification | Local execution only; not vendored or redistributed by Servo. |
| MTMT source | `.gitmodules` points to `eraserNut/MTMT`; directory is present without a license file | Unresolved | Not copied/invoked. Commercial and redistribution status unknown. |
| MTMT/ResNeXt weights | external Google Drive/repository links | No weight license in local tree; files absent | Automatic download prohibited; shadow backend unsupported. |
| MMSegmentation/MMCV source | external packages; files absent | Unresolved for selected versions | Not installed by this integration. |
| SegFormer Cityscapes checkpoint | path referenced by configs; file absent | Checkpoint and training-dataset terms not recorded locally | Automatic download prohibited; semantic backend unsupported. |
| PhotoWCT source | `datasets/stylize_tools/**` | No separate license file found | Do not copy outside external backend pending provenance audit. |
| `photo_wct.pth` | local file, SHA-256 `bedc114a83833de79e92b7166b37bc522db71a30bbfa13d0c4f36387789c8af5` | No license/attribution receipt found | Quarantined as unaudited; not loaded or redistributed. |
| KITTI-360/example datasets | external, absent | Dataset-specific terms required | Not downloaded or redistributed. |
| Style images/panoramas | user/external inputs | Per-file license required | Bundle must store hash, source and redistribution permission. None selected. |

The qualification consumed no MTMT, semantic, stylization, panorama, or effect checkpoint. Its newly trained checkpoint is local and hash-receipted. The root MIT license does not establish third-party checkpoint, dataset, submodule, or user-image rights.
