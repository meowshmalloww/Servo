# ClimateNeRF validation

Publication gates are effect-specific; one attractive image is insufficient.

- Scene: registered PSNR/SSIM, finite RGB/depth/normals/semantics, transient leakage, interpolation stability and capture-envelope coverage.
- Smog: monotonic density/depth transmission, foreground/background ordering, adjacent-view and temporal stability.
- Flood: plane/up alignment, boundary stability, normal/grazing Fresnel behavior, refraction/TIR, seeded wave reproducibility and continuity, no NaN/Inf, reflection support and AA.
- Snow: upward-facing selection, semantic/sky exclusion, sheltered visibility, coverage/thickness monotonicity, bounds, shadow alignment and multi-view stability.
- Style: semantic restriction, appearance change, frozen geometry/drift bound, view consistency and road/sign protection.
- Native/reference: fixed world, camera, seed, time and parameters; compare masks, transmission, boundary, reflection tendency, snow coverage, RGB and temporal behavior with effect-specific tolerance. Pixel identity is not expected across representations.

CPU tests cover source receipts, strict schemas, visual/physical separation, smog monotonicity, plane/water masks, Fresnel, refraction/TIR, deterministic waves, snow candidate rejection, metaballs, job transitions/cancellation/reattachment and bundle tamper detection. The isolated backend imported `tinycudann`, `vren`, and `torch_scatter` on the RTX 4080, executed one real optimizer step, validated 47 held-out views, saved a checkpoint, and rendered 47 official smog RGB/depth pairs. This is execution qualification only: PSNR 13.75 dB and SSIM 0.281 are quality-rejected, so no weather bundle or UI activation is permitted.
