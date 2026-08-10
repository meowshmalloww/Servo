# Reconstruction evidence assets

## Gerrard Hall observed-path audit

Files:

- `gerrard-observed-path-audit.mp4` -- 6.63 seconds, H.264, 1280 x 278, 30 FPS, 4,232,169 bytes, SHA-256 `0825fde2d878009e2f2d5b21bd88c5f6c8d0b18d7e94abdb46351087088a5cb6`.
- `gerrard-observed-path-audit-preview.jpg` -- linked README preview, 70,071 bytes, SHA-256 `233deca4cce208e389d80bed12d3eef6090d4e567bfd9d0531fa5e82ea2508b8`.

Servo generated the audit from the 2026-08-10 Fidelity r3 world. It renders 199 poses interpolated between 100 registered cameras and presents three synchronized panels: RGB appearance, composited expected depth, and a line-of-sight depth-spread proxy. It does not extrapolate outside the registered camera path and must not be interpreted as metric depth, free-space, or collision certification.

The input photographs are the [COLMAP Gerrard Hall example dataset](https://colmap.github.io/datasets.html), described by COLMAP as 100 high-resolution photographs captured at UNC Chapel Hill. The upstream page provides the dataset for download but does not state a separate license for the photographs. These two derived media files are included solely as attributed reconstruction-evaluation evidence, are not covered by Servo's GPLv3 code license, and remain subject to any rights in the source dataset. Replace them with a contributor-owned capture before a distribution that requires an explicit media license grant.
