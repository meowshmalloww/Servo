# CARLA / Project Chrono Sedan attribution

`CarlaChronoSedan.glb` is a mechanical repackaging of the Project Chrono
sedan body, rim, and tire visualization meshes distributed with CARLA 0.9.16.
It is not a manufacturer-certified CAD model and does not represent a named
consumer vehicle.

- CARLA project: https://github.com/carla-simulator/carla
- Project Chrono: https://github.com/projectchrono/chrono
- Original packaged paths: `Co-Simulation/Chrono/Vehicles/sedan/`
- Transformation: the body and four wheel assemblies were combined, their
  coordinate frame was changed to Servo X-lateral/Y-up/Z-forward, and the tire
  bottoms were aligned to local ground height zero. Geometry was not replaced
  or generated.

Project Chrono is distributed under its BSD 3-Clause license. CARLA-specific
code is MIT licensed and CARLA-specific assets are CC BY licensed. Preserve
the upstream notices when redistributing this derived asset.
