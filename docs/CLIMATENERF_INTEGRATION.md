# ClimateNeRF integration

Servo keeps three distinct concepts:

1. **ClimateNeRF Reference** is the original auxiliary hash-grid NeRF and weather algorithms in an isolated Python worker. It requires calibrated images, COLMAP cameras, `tinycudann`, `vren`, and effect-specific evidence/checkpoints.
2. **ClimateNeRF Native** is a future QRhi/Vulkan approximation that consumes generated layers and renderer depth. It must be parity-tested and is not mathematically identical by default.
3. **Baked Climate World** is an immutable sidecar bundle linked to an unchanged Gaussian base world.

The current implementation provides an isolated official-code Docker backend, hash-qualified CUDA dependencies, strict dataset/bundle/job schemas, fail-closed world adaptation, immutable publication verification, and a RealityCI weather descriptor. The procedural Gaussian presentation-shader weather and procedural vehicle proxy were removed. Servo does **not** claim native Vulkan ClimateNeRF passes.

The T5 adapter uses 373 camera-referenced source frames and a separately qualified COLMAP reconstruction with 373/373 registered images and 77,329 sparse points. The original T5 Gaussian world remains unchanged and has unknown monocular scale. A one-step official ClimateNeRF qualification completed, but its held-out PSNR 13.75 dB and SSIM 0.281 failed the 20 dB/0.70 quality gate; its opaque-beige smog render is retained only as rejected evidence and is not exposed in Servo's UI. Generated weather is never observed weather, a forecast, CFD, hydrology, collision geometry, friction, measured flood depth, or snow mass.

## Data flow

`world.json + cameras.json + registered frames` → dataset audit → isolated reference worker → validation → immutable `servo.climate-weather/v1` sidecar → hash-verified base world/layers → native or baked observation source.

No step mutates the base PLY, manifest, cameras, or source images. Hard links are preferred for datasets, with safe copies as fallback.
