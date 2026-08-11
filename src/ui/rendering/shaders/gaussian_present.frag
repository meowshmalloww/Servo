#version 450

layout(location = 0) in vec2 textureCoordinate;
layout(binding = 0) uniform sampler2D hdrWorld;
layout(location = 0) out vec4 fragmentColor;

void main()
{
    // gsplat optimizes and composites display-referred RGB in floating point.
    // Preserve values above one during blending, then clamp once at the final
    // presentation boundary.  Clamping each Gaussian changes highlights and
    // causes view-dependent color errors; allowing Qt Quick to implicitly
    // convert the unclamped RGBA16F item instead washes out bright scenes.
    vec4 color = texture(hdrWorld, textureCoordinate);
    fragmentColor = vec4(clamp(color.rgb, vec3(0.0), vec3(1.0)), 1.0);
}
