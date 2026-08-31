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

vec3 worldRay()
{
    // The directional texture is an observed-only equirectangular sky map.
    // Reconstruct the world ray from the same camera projection that placed
    // the Gaussian quads; translation deliberately does not participate.
    const vec2 ndc = textureCoordinate * 2.0 - 1.0;
    const vec3 cameraDirection = normalize(vec3(
        ndc.x / projectionMatrix[0][0],
        ndc.y / projectionMatrix[1][1],
        -1.0));
    return normalize(transpose(mat3(viewMatrix)) * cameraDirection);
}

vec3 observedDirectionalBackground(vec3 worldDirection)
{
    const float u = fract(atan(worldDirection.x, worldDirection.z) / (2.0 * PI) + 0.5);
    const float v = acos(clamp(worldDirection.y, -1.0, 1.0)) / PI;
    const vec4 observed = texture(observedDirectionalEnvironment, vec2(u, v));
    return mix(environmentFallback.rgb, observed.rgb, observed.a);
}

vec3 timeOfDayGrade(vec3 color)
{
    float hour = clamp(stabilization.z, 0.0, 24.0);
    float intensity = clamp(stabilization.w, 0.0, 2.0);
    float sunAltitude = sin((hour - 6.0) * PI / 12.0);
    float daylight = smoothstep(-0.18, 0.20, sunAltitude);
    float twilight = exp(-pow(sunAltitude / 0.22, 2.0));
    vec3 nightColor = color * vec3(0.10, 0.16, 0.28) + vec3(0.003, 0.006, 0.014);
    vec3 dayColor = color * (0.45 + 0.55 * intensity);
    vec3 graded = mix(nightColor, dayColor, daylight);
    graded += color * vec3(0.19, 0.075, 0.018) * twilight * intensity;
    return max(graded, vec3(0.0));
}

vec3 generatedSun(vec3 direction)
{
    float hour = clamp(stabilization.z, 0.0, 24.0);
    float intensity = clamp(stabilization.w, 0.0, 2.0);
    float altitude = (sin((hour - 6.0) * PI / 12.0)) * (0.48 * PI);
    float azimuth = (hour / 24.0) * 2.0 * PI - 0.5 * PI;
    vec3 up = normalize(weather.xyz);
    vec3 east = abs(up.y) < 0.95 ? normalize(cross(vec3(0.0, 1.0, 0.0), up))
                                 : vec3(1.0, 0.0, 0.0);
    vec3 north = normalize(cross(up, east));
    vec3 horizontal = cos(azimuth) * east + sin(azimuth) * north;
    vec3 sunDirection = normalize(cos(altitude) * horizontal + sin(altitude) * up);
    float aboveHorizon = smoothstep(-0.05, 0.08, sin(altitude));
    float disc = smoothstep(cos(0.012), cos(0.004), dot(direction, sunDirection));
    float glow = pow(max(dot(direction, sunDirection), 0.0), 320.0);
    vec3 sunColor = mix(vec3(1.0, 0.38, 0.12), vec3(1.0, 0.91, 0.68), aboveHorizon);
    return sunColor * (disc * 2.4 + glow * 0.32) * intensity * aboveHorizon;
}

void main()
{
    // gsplat optimizes and composites display-referred RGB in floating point.
    // Preserve values above one during blending, then clamp once at the final
    // presentation boundary.  Clamping each Gaussian changes highlights and
    // causes view-dependent color errors; allowing Qt Quick to implicitly
    // convert the unclamped RGBA16F item instead washes out bright scenes.
    const vec4 color = texture(hdrWorld, textureCoordinate);
    const vec3 direction = worldRay();
    const vec3 environment = timeOfDayGrade(observedDirectionalBackground(direction))
                             + generatedSun(direction);
    const vec3 composited = color.rgb
                            + (1.0 - clamp(color.a, 0.0, 1.0))
                                  * environment;
    fragmentColor = vec4(clamp(composited, vec3(0.0), vec3(1.0)), 1.0);
}
