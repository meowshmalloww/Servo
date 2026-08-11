# Reconstruction evidence assets

## Yosemite road Fidelity r6 observed-path audit

Files:

- `yosemite-road-r6-observed-path-audit.mp4` -- 24.83 seconds, H.264, 1920 x 360, 30 FPS, 40,607,556 bytes, SHA-256 `6de9a53ecadc9712279336328bf8781059d17763503cf29ce61c98d0fa93de81`.
- `yosemite-road-r6-observed-path-audit.gif` -- 8-second inline README excerpt, 1440 x 270, 8 FPS, 15,568,191 bytes, SHA-256 `1beef2ad0642d82c7307f2b6a805d698ae7add530136e7e2e2f4789d0d3db762`.
- `yosemite-road-r6-observed-path-audit-preview.jpg` -- 1920 x 360 static fallback preview, 191,780 bytes, SHA-256 `fbc6f9a8c6cf9cf751ae24832d710ff86b54bde15f95ab48d0a9ca39dda1a513`.

Servo generated the audit from the 2026-08-11 Fidelity r6 world. It reloads the published SH3 PLY and renders 745 poses covering all 373 registered cameras plus an interpolated pose between each adjacent pair. The audit presents RGB appearance, composited expected depth, and a line-of-sight depth-spread proxy. It does not extrapolate outside the registered camera path and must not be interpreted as metric depth, free space, unseen geometry, or collision certification.

The contributor supplied and authorized use of the source road capture for this project and its public demonstration. These derived evidence assets document the measured reconstruction result; they do not expand Servo's GPLv3 code license to unrelated source media.

## Gerrard Hall observed-path audit

Files:

- `gerrard-observed-path-audit.mp4` -- 6.63 seconds, H.264, 1920 x 418, 30 FPS, 19,239,784 bytes, SHA-256 `54975f9d081d3697491d4d667e48f2f0ea63c2465009f8944356894121b63ec7`.
- `gerrard-observed-path-audit.gif` -- inline README animation, 6.63 seconds, 1440 x 314, 8 FPS, 14,428,079 bytes, SHA-256 `89ea294ba92419a73ad4b58d3be3e47ab03deefcdb9225468eaa976e53a3be4b`.
- `gerrard-observed-path-audit-preview.jpg` -- 1920 x 418 static fallback preview, 183,969 bytes, SHA-256 `104fa97c7361824684480dbcdd8951f04e71f827e15895cf2dffe9915901fd56`.

Servo generated the audit from the 2026-08-10 Fidelity r3 world. It renders 199 poses interpolated between 100 registered cameras and presents three synchronized panels: RGB appearance, composited expected depth, and a line-of-sight depth-spread proxy. It does not extrapolate outside the registered camera path and must not be interpreted as metric depth, free-space, or collision certification.

The input photographs are the [COLMAP Gerrard Hall example dataset](https://colmap.github.io/datasets.html), described by COLMAP as 100 high-resolution photographs captured at UNC Chapel Hill. The upstream page provides the dataset for download but does not state a separate license for the photographs. These three derived media files are included solely as attributed reconstruction-evaluation evidence, are not covered by Servo's GPLv3 code license, and remain subject to any rights in the source dataset. Replace them with a contributor-owned capture before a distribution that requires an explicit media license grant.
