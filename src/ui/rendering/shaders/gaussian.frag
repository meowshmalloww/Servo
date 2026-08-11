#version 450

layout(location = 0) in vec2 localCoordinate;
layout(location = 1) in vec3 gaussianColor;
layout(location = 2) in float gaussianOpacity;
layout(location = 0) out vec4 fragmentColor;

void main()
{
    float power = -0.5 * dot(localCoordinate, localCoordinate);
    if (power > 0.0)
        discard;
    float alpha = min(0.999, gaussianOpacity * exp(power));
    if (alpha < (1.0 / 255.0))
        discard;
    fragmentColor = vec4(gaussianColor * alpha, alpha);
}
