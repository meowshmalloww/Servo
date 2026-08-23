#version 450

layout(location = 0) out vec2 localCoordinate;
layout(location = 1) out vec3 gaussianColor;
layout(location = 2) out float gaussianOpacity;

layout(std140, binding = 0) uniform CameraUniforms {
    mat4 viewMatrix;
    mat4 projectionMatrix;
    vec4 cameraPosition;
    vec4 viewportFocal;
    vec4 parameters;
    vec4 environmentFallback;
};

layout(std430, binding = 1) readonly buffer ProjectedGaussians {
    vec4 projected[];
};

layout(std430, binding = 2) readonly buffer GaussianOrder {
    uint order[];
};

vec2 quadCorner(int vertexIndex)
{
    const vec2 corners[6] = vec2[6](
        vec2(-1.0, -1.0), vec2(1.0, -1.0), vec2(1.0, 1.0),
        vec2(-1.0, -1.0), vec2(1.0, 1.0), vec2(-1.0, 1.0));
    return corners[vertexIndex];
}

void main()
{
    uint gaussianIndex = order[gl_InstanceIndex];
    uint base = gaussianIndex * 4u;
    vec4 clipMean = projected[base];
    vec4 axes = projected[base + 1u];
    vec4 colorOpacity = projected[base + 2u];
    vec4 metadata = projected[base + 3u];
    if (metadata.y < 0.5) {
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        localCoordinate = vec2(99.0);
        gaussianColor = vec3(0.0);
        gaussianOpacity = 0.0;
        return;
    }

    vec2 corner = quadCorner(gl_VertexIndex);
    vec2 pixelOffset = axes.xy * corner.x + axes.zw * corner.y;
    vec2 projectionSign = vec2(sign(projectionMatrix[0][0]),
                               sign(projectionMatrix[1][1]));
    vec2 clipOffset = projectionSign
                      * vec2(pixelOffset.x * 2.0 / viewportFocal.x,
                             pixelOffset.y * 2.0 / viewportFocal.y)
                      * clipMean.w;
    gl_Position = clipMean + vec4(clipOffset, 0.0, 0.0);
    localCoordinate = corner * metadata.x;
    gaussianColor = colorOpacity.rgb;
    gaussianOpacity = colorOpacity.a;
}
