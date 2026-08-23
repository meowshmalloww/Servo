# Gaussian renderer stability

Servo's native Explore renderer uses Qt 6.11.1 QRhi compute passes on Vulkan.
Every displayed frame projects the complete SH3 Gaussian payload, performs a
stable four-pass GPU radix sort, then hardware-blends premultiplied ellipses
into an RGBA16F accumulation target. The projection, sorting, and draw use one
camera snapshot, so there is no stale CPU-sort frame.

## Artifact-parity global key

The global radix key is positive camera-space Z, matching the gsplat 1.5.3
rasterizer used to train and validate Servo's PLY. Positive float bits are
monotonic; bit inversion makes the ascending radix pass produce the far-to-near
order required by the current premultiplied hardware blend.

Camera distance is a valid Khronos interchange baseline, but it is not the
producing policy for this artifact. A direct r6 comparison changed more than
15% of pixels by over 1% RGB and reduced registered-camera PSNR when radial
sorting was substituted after training. Servo therefore preserves artifact
parity until a tile/per-pixel renderer is paired with matched training.

`GaussianSortStabilityTests` protects three invariants:

- ascending radix keys remain far-to-near for the existing blend equation;
- the view-depth key follows the producing camera under rotation;
- the production preprocess shader still implements the tested key.

## Explicit remaining limit

This is not the full
[`StopThePop`](https://arxiv.org/abs/2402.00525) hierarchical rasterizer.
Hardware blending still consumes one global order. Off-center overlapping
ellipses can require a different order per pixel, and camera translation can
legitimately change radial order. StopThePop addresses that with tile culling,
per-tile depth evaluation, shared `4 x 4` and `2 x 2` queues, and per-pixel
queues in a compute-mode rasterizer. Their paper reports that a simple local
16--24-element resorting window removes most visible popping but costs
approximately 2--6x, while their complete hierarchy averages 4% overhead.

Completing that architecture in QRhi requires a compute rasterizer that builds
tile-contribution lists and writes the final color image. Qt documents storage
buffer load/store as guaranteed in compute pipelines but not generally safe in
graphics fragment stages, so a fragment-shader k-buffer is not a portable QRhi
shortcut. Servo must retain the current same-frame radix path until the compute
replacement meets image-consistency and frame-time gates.

The renderer cannot repair incorrect or unobserved scene geometry. Floaters,
holes during camera translation, sky splats, and unstable road surfaces must be
fixed or rejected by reconstruction and geometry-quality gates.
