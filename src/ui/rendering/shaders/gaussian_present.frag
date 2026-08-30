#version 450

layout(location = 0) in vec2 textureCoordinate;
layout(binding = 0) uniform sampler2D hdrWorld;
layout(binding = 1) uniform sampler2D observedDirectionalEnvironment;

layout(std140, binding = 2) uniform CameraUniforms {
    mat4 viewMatrix;
    mat4 projectionMatrix;
    vec4 cameraPosition;
    vec4 viewportFocal;
    vec4 parameters;
    vec4 environmentFallback;
    vec4 stabilization;
    vec4 weather;
};

layout(location = 0) out vec4 fragmentColor;

const float PI = 3.14159265358979323846;

vec3 observedDirectionalBackground()
{
    // The directional texture is an observed-only equirectangular sky map.
    // Reconstruct the world ray from the same camera projection that placed
    // the Gaussian quads; translation deliberately does not participate.
    const vec2 ndc = textureCoordinate * 2.0 - 1.0;
    const vec3 cameraDirection = normalize(vec3(
        ndc.x / projectionMatrix[0][0],
        ndc.y / projectionMatrix[1][1],
        -1.0));
    const vec3 worldDirection = normalize(transpose(mat3(viewMatrix)) * cameraDirection);
    const float u = fract(atan(worldDirection.x, worldDirection.z) / (2.0 * PI) + 0.5);
    const float v = acos(clamp(worldDirection.y, -1.0, 1.0)) / PI;
    const vec4 observed = texture(observedDirectionalEnvironment, vec2(u, v));
    return mix(environmentFallback.rgb, observed.rgb, observed.a);
}

void main()
{
    // gsplat optimizes and composites display-referred RGB in floating point.
    // Preserve values above one during blending, then clamp once at the final
    // presentation boundary.  Clamping each Gaussian changes highlights and
    // causes view-dependent color errors; allowing Qt Quick to implicitly
    // convert the unclamped RGBA16F item instead washes out bright scenes.
    const vec4 color = texture(hdrWorld, textureCoordinate);
    const vec3 composited = color.rgb
                            + (1.0 - clamp(color.a, 0.0, 1.0))
                                  * observedDirectionalBackground();
    fragmentColor = vec4(clamp(composited, vec3(0.0), vec3(1.0)), 1.0);
}
