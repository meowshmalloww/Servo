# ClimateNeRF and Servo 3DGS rendering

ClimateNeRF's auxiliary NeRF predicts density, RGB, semantics, normals and depth. Servo's base world remains 3D Gaussians rendered through QRhi/Vulkan. Gaussian quaternion orientation is not accepted as a certified surface normal.

Native smog may use expected finite-surface depth with `T(d)=exp(-sigma*d)` in linear color, but only after bundle/readiness verification. Native water requires a validated plane, ray/depth intersection, mirrored Gaussian-camera reflection target, deterministic FFT/TMA wave normals, Fresnel, glossy response, refraction/clarity, boundary AA and confidence output. Native snow requires a separate persistent 3D layer generated from validated surfaces/normals/visibility—not particles or a 2D mask.

None of those native passes is complete today. The former `gaussian_present.frag` weather modes were deleted; the presentation shader now only composites the original Gaussian render. Servo remains locked to Clear until a hash-verified, quality-accepted ClimateNeRF bundle has a real renderer consumer. No OpenGL fallback or QML-per-splat path is permitted.
