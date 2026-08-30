# T5 ClimateNeRF snow

Servo has two deliberately separate snow paths:

1. the working hackathon path: CARLA applies authoritative reduced tire
   friction and records gravity/contact evidence while Servo renders a
   provenance-labelled, generated/inferred surface condition; and
2. the upstream ClimateNeRF path below, which is the higher-fidelity visual
   target but remains unavailable until its semantic checkpoint passes the
   image-quality gate.

The working path is not advertised as ClimateNeRF output. In the verified
session `sim-d8e994ae412a481a`, 90% accumulation produced a 0.478 tire-friction
multiplier, measured 9.769 m/s² initial IMU acceleration against CARLA's
9.81 m/s² reference, passed ground contact, completed 99.2% of the route, and
recorded zero collisions. `weather_receipt.visual_provenance` is
`generated-inferred-surface` and `climatenerf_qualified=false`.

The upstream ClimateNeRF qualification sequence is:

1. train the T5 scene with semantic prediction enabled;
2. run upstream `make_snow.py` for the scene;
3. render the resulting `model_with_snow` checkpoint with
   `render.py --simulate snow`;
4. qualify the rendered frames and publish their hashes;
5. only then enable the Snow selection in Servo.

The current RGB-only T5 ClimateNeRF checkpoint has `render_semantic=False` and
is not a valid upstream snow input. `tools/climate/reference_backend.py
make-snow` rejects that checkpoint before expensive processing begins. This
failure does not disable the separately labelled CARLA/inferred-surface path.

All required source/runtime inputs are stored under Servo:

- ClimateNeRF source: `third_party/Climate_NeRF`
- mmsegmentation config source: `third_party/mmsegmentation`
- SegFormer checkpoint: `runtime/models/mmseg`
- T5 COLMAP dataset: `simulations/runtime/t5/climate-dataset`
- Docker build: `tools/climate/Dockerfile.climatenerf`
- audited identities: `runtime/vendor-manifest.json`

The semantic base command is:

```powershell
python -m tools.climate.reference_backend train `
  --dataset simulations/runtime/t5/climate-dataset `
  --output simulations/runtime/t5/climate-snow-base-v1 `
  --config tools/climate/configs/YosemiteT5SnowBase.txt `
  --experiment yosemite-t5-snow-base-v1 `
  --semantic-config third_party/mmsegmentation/configs/segformer/segformer_mit-b5_8x1_1024x1024_160k_cityscapes.py `
  --semantic-checkpoint runtime/models/mmseg/segformer_mit-b5_8x1_1024x1024_160k_cityscapes_20211206_072934-87a052ec.pth `
  --semantic-downsample 0.25
```

After that checkpoint is quality accepted, run upstream snow fitting through
the Servo launcher:

```powershell
python -m tools.climate.reference_backend make-snow `
  --dataset simulations/runtime/t5/climate-dataset `
  --output simulations/runtime/t5/climate-snow-v1 `
  --config tools/climate/configs/YosemiteT5SnowBase.txt `
  --experiment yosemite-t5-snow-v1 `
  --checkpoint PATH_TO_ACCEPTED_SEMANTIC_CHECKPOINT `
  --epochs 20 --mb-size 0.005
```

ClimateNeRF changes rendered appearance. It does not create CARLA collision
geometry, tire friction, snow depth physics, or a snow-modified 3D Gaussian
checkpoint. Those capabilities must remain separately labelled.
