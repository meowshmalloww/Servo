# Third-party software

## CARLA

Servo integrates with an externally installed CARLA packaged runtime and does not redistribute CARLA binaries or source. CARLA is Copyright (c) 2017 Computer Vision Center (CVC) at the Universitat Autonoma de Barcelona (UAB), licensed under the MIT License. See the CARLA distribution’s `LICENSE` and [CARLA repository](https://github.com/carla-simulator/carla).

Bundled CARLA BehaviorAgent modules are imported from the registered external runtime; their source is not copied into Servo. Users are responsible for retaining the license files included with their CARLA distribution.

Other dependencies retain the licenses declared by their existing package manifests and distributions.

## Khronos glTF vehicle assets

Servo bundles a scene-trimmed runtime derivative of the Khronos glTF Sample
Assets `ToyCar.glb` under CC0-1.0 for the native drive visual. Its exact source,
the mechanical scene-node change, and both SHA-256 values are recorded in
`src/ui/assets/vehicles/ToyCar.LICENSE.md`. The older `CarConcept.glb` sample
is retained under its upstream CC-BY-4.0 and Khronos legal-mark terms; its
notice is in `src/ui/assets/vehicles/CarConcept.LICENSE.md`.

## OpenX Volvo EX30 vehicle asset

Servo's default native-drive vehicle is the OpenX Assets 2024 Volvo EX30
simulation model from release `20250821`. The upstream metadata records 59,354
triangles, 15 authored meshes, physical dimensions, axle positions, and a
2,000 kg mass. It is distributed under `MPL-2.0 AND CC-BY-4.0`; attribution,
source identity, hashes, and the trademark disclaimer are recorded in
`src/ui/assets/vehicles/OpenXVolvoEX30.LICENSE.md`.

## ClimateNeRF

Servo does not redistribute ClimateNeRF source or checkpoints. Its independent
weather contract can bind a separately qualified external ClimateNeRF output,
while the active native T5/CARLA snow path remains explicitly generated or
inferred and does not claim to execute the upstream method. The audited local
source matches official commit `3a3e04ae58578983a51dd30c5650c1d61f4b9b22`
after newline normalization. ClimateNeRF root source is MIT licensed, copyright
2022 James Lin. Docker and WSL are not required by Servo's active Windows path.

ClimateNeRF submodules, external packages, checkpoints, datasets, panoramas and
style images are separate assets. MTMT/ResNeXt, SegFormer/mmsegmentation,
PhotoWCT weights, panoramas and style imagery remain disabled and are never
downloaded automatically. See `docs/CLIMATENERF_LICENSE_AUDIT.md`.
