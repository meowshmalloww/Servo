#include "GaussianSplatView.h"
#include "GaussianPathSmoothing.h"

#include <QElapsedTimer>
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QImage>
#include <QMatrix4x4>
#include <QMetaObject>
#include <QPointer>
#include <QQuaternion>
#include <QRegularExpression>
#include <QtConcurrent>
#include <QtEndian>
#include <rhi/qrhi.h>
#include <rhi/qshader.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <memory>
#include <numbers>
#include <vector>

struct GaussianSceneData
{
    QByteArray payload;
    QVector<QVector3D> centers;
    QVector3D backgroundColorSrgb { 0.0f, 0.0f, 0.0f };
    QImage observedDirectionalEnvironment;
    QVector3D initialPosition { 0.0f, 0.0f, 2.0f };
    QVector3D initialForward { 0.0f, 0.0f, -1.0f };
    QVector3D initialUp { 0.0f, 1.0f, 0.0f };
    QVector3D navigationUp { 0.0f, 1.0f, 0.0f };
    QVector<QVector3D> cameraPath;
    QVector<QVector3D> cameraPathForwards;
    QVector<float> cameraPathDistances;
    float pathOffsetLimit = 0.02f;
    float verticalFov = 52.0f;
    float movementSpeed = 0.08f;
    float visualizationFarDepth = 16.0f;
    int count = 0;
};

namespace {

constexpr qsizetype kFloatStride = 59;
constexpr qsizetype kByteStride = kFloatStride * qsizetype(sizeof(float));
constexpr qint64 kMaximumGaussianCount = 5'000'000;
constexpr quint32 kComputeGroupSize = 256;
constexpr quint32 kRadixPassCount = 4;
constexpr float kNearPlane = 0.01f;

const QStringList kExpectedProperties {
    QStringLiteral("x"), QStringLiteral("y"), QStringLiteral("z"),
    QStringLiteral("f_dc_0"), QStringLiteral("f_dc_1"), QStringLiteral("f_dc_2"),
    QStringLiteral("f_rest_0"), QStringLiteral("f_rest_1"), QStringLiteral("f_rest_2"),
    QStringLiteral("f_rest_3"), QStringLiteral("f_rest_4"), QStringLiteral("f_rest_5"),
    QStringLiteral("f_rest_6"), QStringLiteral("f_rest_7"), QStringLiteral("f_rest_8"),
    QStringLiteral("f_rest_9"), QStringLiteral("f_rest_10"), QStringLiteral("f_rest_11"),
    QStringLiteral("f_rest_12"), QStringLiteral("f_rest_13"), QStringLiteral("f_rest_14"),
    QStringLiteral("f_rest_15"), QStringLiteral("f_rest_16"), QStringLiteral("f_rest_17"),
    QStringLiteral("f_rest_18"), QStringLiteral("f_rest_19"), QStringLiteral("f_rest_20"),
    QStringLiteral("f_rest_21"), QStringLiteral("f_rest_22"), QStringLiteral("f_rest_23"),
    QStringLiteral("f_rest_24"), QStringLiteral("f_rest_25"), QStringLiteral("f_rest_26"),
    QStringLiteral("f_rest_27"), QStringLiteral("f_rest_28"), QStringLiteral("f_rest_29"),
    QStringLiteral("f_rest_30"), QStringLiteral("f_rest_31"), QStringLiteral("f_rest_32"),
    QStringLiteral("f_rest_33"), QStringLiteral("f_rest_34"), QStringLiteral("f_rest_35"),
    QStringLiteral("f_rest_36"), QStringLiteral("f_rest_37"), QStringLiteral("f_rest_38"),
    QStringLiteral("f_rest_39"), QStringLiteral("f_rest_40"), QStringLiteral("f_rest_41"),
    QStringLiteral("f_rest_42"), QStringLiteral("f_rest_43"), QStringLiteral("f_rest_44"),
    QStringLiteral("opacity"), QStringLiteral("scale_0"), QStringLiteral("scale_1"),
    QStringLiteral("scale_2"), QStringLiteral("rot_0"), QStringLiteral("rot_1"),
    QStringLiteral("rot_2"), QStringLiteral("rot_3")
};

struct LoadResult
{
    std::shared_ptr<const GaussianSceneData> scene;
    QString error;
};

float valueAt(const char *record, qsizetype index)
{
    quint32 bits = 0;
    std::memcpy(&bits, record + index * qsizetype(sizeof(float)), sizeof(bits));
    bits = qFromLittleEndian(bits);
    float value = 0.0f;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

QVector3D normalizedOr(const QVector3D &value, const QVector3D &fallback)
{
    const float lengthSquared = value.lengthSquared();
    return std::isfinite(lengthSquared) && lengthSquared > 1e-10f
               ? value / std::sqrt(lengthSquared)
               : fallback;
}

QShader loadShader(const QString &path)
{
    QFile file(path);
    return file.open(QIODevice::ReadOnly) ? QShader::fromSerialized(file.readAll()) : QShader();
}

bool readInitialCamera(const QString &plyPath,
                       QVector3D *position,
                       QVector3D *forward,
                       QVector3D *up,
                       QVector3D *navigationUp,
                       float *verticalFov,
                       float *movementSpeed,
                       QVector<QVector3D> *cameraPath,
                       QVector<QVector3D> *cameraPathForwards,
                       QVector<float> *cameraPathDistances,
                       float *pathOffsetLimit)
{
    QFile file(QFileInfo(plyPath).dir().filePath(QStringLiteral("cameras.json")));
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text))
        return false;
    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(file.readAll(), &parseError);
    const QJsonArray cameras = document.object().value(QStringLiteral("cameras")).toArray();
    if (parseError.error != QJsonParseError::NoError || cameras.isEmpty())
        return false;
    const QJsonObject camera = cameras.first().toObject();
    const QJsonArray matrix = camera.value(QStringLiteral("cameraToWorldNormalized")).toArray();
    const QJsonArray calibration = camera.value(QStringLiteral("calibration")).toArray();
    if (matrix.size() != 4 || calibration.size() != 3)
        return false;
    std::array<std::array<float, 4>, 4> values {};
    for (int row = 0; row < 4; ++row) {
        const QJsonArray sourceRow = matrix.at(row).toArray();
        if (sourceRow.size() != 4)
            return false;
        for (int column = 0; column < 4; ++column) {
            const double value = sourceRow.at(column).toDouble(
                std::numeric_limits<double>::quiet_NaN());
            if (!std::isfinite(value))
                return false;
            values[row][column] = float(value);
        }
    }
    *position = QVector3D(values[0][3], values[1][3], values[2][3]);
    *forward = normalizedOr(QVector3D(values[0][2], values[1][2], values[2][2]),
                            QVector3D(0.0f, 0.0f, -1.0f));
    *up = normalizedOr(-QVector3D(values[0][1], values[1][1], values[2][1]),
                       QVector3D(0.0f, 1.0f, 0.0f));
    const QJsonArray intrinsicsRow = calibration.at(1).toArray();
    const double fy = intrinsicsRow.size() == 3 ? intrinsicsRow.at(1).toDouble() : 0.0;
    const double height = camera.value(QStringLiteral("height")).toDouble();
    if (fy > 0.0 && height > 0.0)
        *verticalFov = float(2.0 * std::atan(height / (2.0 * fy)) * 180.0 / std::numbers::pi);

    std::vector<float> cameraSteps;
    QVector3D previousPosition;
    QVector3D upAccumulator;
    bool hasPreviousPosition = false;
    QString videoGroup;
    bool coherentVideoPath = true;
    if (cameras.size() > 1)
        cameraSteps.reserve(size_t(cameras.size() - 1));
    for (const QJsonValue &cameraValue : cameras) {
        const QJsonObject cameraObject = cameraValue.toObject();
        const QString imageName = cameraObject.value(QStringLiteral("image")).toString();
        const QString group = imageName.section(QLatin1Char('/'), 0, 0);
        if (!group.startsWith(QStringLiteral("video-")))
            coherentVideoPath = false;
        if (videoGroup.isEmpty())
            videoGroup = group;
        else if (group != videoGroup)
            coherentVideoPath = false;
        const QJsonArray cameraMatrix = cameraObject
                                                  .value(QStringLiteral("cameraToWorldNormalized"))
                                                  .toArray();
        if (cameraMatrix.size() != 4)
            continue;
        const QJsonArray row0 = cameraMatrix.at(0).toArray();
        const QJsonArray row1 = cameraMatrix.at(1).toArray();
        const QJsonArray row2 = cameraMatrix.at(2).toArray();
        if (row0.size() != 4 || row1.size() != 4 || row2.size() != 4)
            continue;
        const double px = row0.at(3).toDouble(
            std::numeric_limits<double>::quiet_NaN());
        const double py = row1.at(3).toDouble(
            std::numeric_limits<double>::quiet_NaN());
        const double pz = row2.at(3).toDouble(
            std::numeric_limits<double>::quiet_NaN());
        const double fx = row0.at(2).toDouble(
            std::numeric_limits<double>::quiet_NaN());
        const double fy = row1.at(2).toDouble(
            std::numeric_limits<double>::quiet_NaN());
        const double fz = row2.at(2).toDouble(
            std::numeric_limits<double>::quiet_NaN());
        const double ux = row0.at(1).toDouble(
            std::numeric_limits<double>::quiet_NaN());
        const double uy = row1.at(1).toDouble(
            std::numeric_limits<double>::quiet_NaN());
        const double uz = row2.at(1).toDouble(
            std::numeric_limits<double>::quiet_NaN());
        if (!std::isfinite(px) || !std::isfinite(py) || !std::isfinite(pz)
            || !std::isfinite(fx) || !std::isfinite(fy) || !std::isfinite(fz)
            || !std::isfinite(ux) || !std::isfinite(uy) || !std::isfinite(uz)) {
            coherentVideoPath = false;
            continue;
        }
        const QVector3D cameraPosition { float(px), float(py), float(pz) };
        QVector3D cameraForward { float(fx), float(fy), float(fz) };
        cameraForward = normalizedOr(cameraForward, *forward);
        QVector3D cameraUp { -float(ux), -float(uy), -float(uz) };
        cameraUp = normalizedOr(cameraUp, *up);
        // Camera poses can differ in pitch and roll, especially for handheld
        // video. A hemisphere-aligned mean gives navigation a stable scene-up
        // direction without assuming that COLMAP's arbitrary world uses +Y.
        if (QVector3D::dotProduct(cameraUp, *up) < 0.0f)
            cameraUp = -cameraUp;
        upAccumulator += cameraUp;
        cameraPath->append(cameraPosition);
        cameraPathForwards->append(cameraForward);
        if (hasPreviousPosition) {
            const float step = (cameraPosition - previousPosition).length();
            if (std::isfinite(step) && step > 1e-6f)
                cameraSteps.push_back(step);
        }
        previousPosition = cameraPosition;
        hasPreviousPosition = true;
    }
    *navigationUp = normalizedOr(upAccumulator, *up);
    if (!cameraSteps.empty()) {
        const auto middle = cameraSteps.begin() + std::ptrdiff_t(cameraSteps.size() / 2);
        std::nth_element(cameraSteps.begin(), middle, cameraSteps.end());
        // Traverse a few registered viewpoints per second. This keeps the
        // default camera inside observed coverage regardless of the scene's
        // arbitrary monocular normalization scale.
        *movementSpeed = std::clamp(*middle * 4.0f, 0.01f, 2.0f);
        *pathOffsetLimit = std::clamp(*middle * 2.5f, 0.005f, 0.12f);
    }
    if (!coherentVideoPath || cameraPath->size() < 2) {
        cameraPath->clear();
        cameraPathForwards->clear();
        cameraPathDistances->clear();
    } else {
        *cameraPath = Servo::smoothNavigationHeights(*cameraPath, *navigationUp);
        cameraPathDistances->reserve(cameraPath->size());
        cameraPathDistances->append(0.0f);
        for (qsizetype index = 1; index < cameraPath->size(); ++index) {
            const float distance = cameraPathDistances->last()
                                   + (cameraPath->at(index) - cameraPath->at(index - 1)).length();
            cameraPathDistances->append(distance);
        }
    }
    return true;
}

LoadResult loadGaussianScene(const QString &path)
{
    LoadResult result;
    Servo::Rendering::GaussianWorldEnvironment environment;
    if (!Servo::Rendering::readGaussianWorldEnvironment(path, &environment, &result.error)) {
        return result;
    }
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        result.error = QStringLiteral("Unable to open the Gaussian PLY: %1").arg(file.errorString());
        return result;
    }
    if (file.size() < 128) {
        result.error = QStringLiteral("The Gaussian PLY is empty or truncated.");
        return result;
    }

    QByteArray header;
    QStringList properties;
    qint64 count = -1;
    bool binaryLittleEndian = false;
    while (!file.atEnd() && header.size() <= 64 * 1024) {
        const QByteArray line = file.readLine();
        header += line;
        const QString text = QString::fromLatin1(line).trimmed();
        if (text == QStringLiteral("format binary_little_endian 1.0"))
            binaryLittleEndian = true;
        else if (text.startsWith(QStringLiteral("element vertex ")))
            count = text.sliced(15).toLongLong();
        else if (text.startsWith(QStringLiteral("property float ")))
            properties.append(text.sliced(15));
        if (text == QStringLiteral("end_header"))
            break;
    }
    if (!header.endsWith("end_header\n") && !header.endsWith("end_header\r\n")) {
        result.error = QStringLiteral("The PLY header is malformed or exceeds 64 KiB.");
        return result;
    }
    if (!binaryLittleEndian || count <= 0 || count > kMaximumGaussianCount
        || properties != kExpectedProperties) {
        result.error = QStringLiteral(
            "Servo Explore requires the verified binary little-endian SH3 Gaussian PLY schema.");
        return result;
    }
    if (count > (std::numeric_limits<qsizetype>::max() / kByteStride)) {
        result.error = QStringLiteral("The Gaussian count exceeds this process's address space.");
        return result;
    }
    const qsizetype payloadBytes = qsizetype(count) * kByteStride;
    if (file.size() != header.size() + payloadBytes) {
        result.error = QStringLiteral("The Gaussian PLY byte length does not match its header.");
        return result;
    }

    auto scene = std::make_shared<GaussianSceneData>();
    scene->backgroundColorSrgb = environment.backgroundColorSrgb;
    scene->observedDirectionalEnvironment = environment.observedDirectionalRgba;
    scene->payload = file.read(payloadBytes);
    if (scene->payload.size() != payloadBytes) {
        result.error = QStringLiteral("The Gaussian PLY could not be read completely.");
        return result;
    }
    scene->centers.resize(count);
    QVector<QVector3D> samples;
    const qsizetype sampleStride = std::max<qsizetype>(1, count / 100'000);
    samples.reserve(int(std::min<qint64>(count, 100'001)));
    for (qint64 index = 0; index < count; ++index) {
        const char *record = scene->payload.constData() + qsizetype(index) * kByteStride;
        bool finite = true;
        for (qsizetype property = 0; property < kFloatStride; ++property) {
            if (!std::isfinite(valueAt(record, property))) {
                finite = false;
                break;
            }
        }
        if (!finite) {
            result.error = QStringLiteral("The Gaussian PLY contains non-finite values at row %1.")
                               .arg(index);
            return result;
        }
        const QVector3D center(valueAt(record, 0), valueAt(record, 1), valueAt(record, 2));
        scene->centers[int(index)] = center;
        if (index % sampleStride == 0)
            samples.append(center);
    }
    scene->count = int(count);

    if (!readInitialCamera(path,
                           &scene->initialPosition,
                           &scene->initialForward,
                           &scene->initialUp,
                           &scene->navigationUp,
                           &scene->verticalFov,
                           &scene->movementSpeed,
                           &scene->cameraPath,
                           &scene->cameraPathForwards,
                           &scene->cameraPathDistances,
                           &scene->pathOffsetLimit)) {
        std::vector<float> xs, ys, zs;
        xs.reserve(samples.size());
        ys.reserve(samples.size());
        zs.reserve(samples.size());
        for (const QVector3D &sample : std::as_const(samples)) {
            xs.push_back(sample.x());
            ys.push_back(sample.y());
            zs.push_back(sample.z());
        }
        std::sort(xs.begin(), xs.end());
        std::sort(ys.begin(), ys.end());
        std::sort(zs.begin(), zs.end());
        const auto percentile = [](const std::vector<float> &values, double fraction) {
            const size_t index = std::min(values.size() - 1,
                                          size_t(fraction * double(values.size() - 1)));
            return values[index];
        };
        const QVector3D minimum(percentile(xs, 0.01), percentile(ys, 0.01), percentile(zs, 0.01));
        const QVector3D maximum(percentile(xs, 0.99), percentile(ys, 0.99), percentile(zs, 0.99));
        const QVector3D center = (minimum + maximum) * 0.5f;
        const float radius = std::max(0.1f, (maximum - minimum).length() * 0.5f);
        scene->initialPosition = center + QVector3D(0.0f, 0.0f, radius * 2.2f);
        scene->initialForward = normalizedOr(center - scene->initialPosition,
                                             QVector3D(0.0f, 0.0f, -1.0f));
        scene->initialUp = QVector3D(0.0f, 1.0f, 0.0f);
        scene->navigationUp = scene->initialUp;
        scene->verticalFov = 52.0f;
    }

    // Use one robust range for the diagnostic depth colors so they do not
    // pulse as the camera moves. This range stays relative because a monocular
    // world has no metric scale without an external scale anchor.
    std::vector<float> positiveDepths;
    positiveDepths.reserve(samples.size());
    const QVector3D initialForward = normalizedOr(scene->initialForward,
                                                   QVector3D(0.0f, 0.0f, -1.0f));
    for (const QVector3D &sample : std::as_const(samples)) {
        const float depth = QVector3D::dotProduct(sample - scene->initialPosition,
                                                  initialForward);
        if (std::isfinite(depth) && depth > kNearPlane)
            positiveDepths.push_back(depth);
    }
    if (!positiveDepths.empty()) {
        std::sort(positiveDepths.begin(), positiveDepths.end());
        const size_t percentileIndex = std::min(
            positiveDepths.size() - 1,
            size_t(0.98 * double(positiveDepths.size() - 1)));
        scene->visualizationFarDepth = std::clamp(positiveDepths[percentileIndex],
                                                  0.25f,
                                                  1000.0f);
    }

    result.scene = std::move(scene);
    return result;
}

struct alignas(16) CameraUniforms
{
    float view[16];
    float projection[16];
    float camera[4];
    float viewportFocal[4];
    float parameters[4];
    float environmentFallback[4];
};

struct alignas(16) RadixConfig
{
    quint32 count = 0;
    quint32 workgroups = 0;
    quint32 shift = 0;
    quint32 reserved = 0;
};

} // namespace

bool Servo::Rendering::readGaussianWorldEnvironment(const QString &plyPath,
                                                     GaussianWorldEnvironment *environment,
                                                     QString *error)
{
    if (!environment) {
        if (error)
            *error = QStringLiteral("The Gaussian environment output is null.");
        return false;
    }
    *environment = GaussianWorldEnvironment {};
    if (error)
        error->clear();
    const auto fail = [error](const QString &message) {
        if (error)
            *error = message;
        return false;
    };

    const QDir bundleDirectory = QFileInfo(plyPath).dir();
    QFile manifestFile(bundleDirectory.filePath(QStringLiteral("world.json")));
    if (!manifestFile.exists())
        return true; // Standalone and pre-manifest PLYs retain the black fallback.
    if (!manifestFile.open(QIODevice::ReadOnly | QIODevice::Text)) {
        return fail(QStringLiteral("Unable to read the Gaussian world manifest: %1")
                        .arg(manifestFile.errorString()));
    }

    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(manifestFile.readAll(), &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
        return fail(QStringLiteral("The Gaussian world manifest is malformed: %1")
                        .arg(parseError.errorString()));
    }

    const QJsonObject manifest = document.object();
    QString pipelineRevision = manifest.value(QStringLiteral("pipelineRevision")).toString();
    if (pipelineRevision.isEmpty()) {
        pipelineRevision = manifest.value(QStringLiteral("training"))
                               .toObject()
                               .value(QStringLiteral("configuration"))
                               .toObject()
                               .value(QStringLiteral("pipelineRevision"))
                               .toString();
    }

    const QJsonValue environmentValue = manifest.value(QStringLiteral("environment"));
    if (environmentValue.isUndefined()) {
        if (pipelineRevision.endsWith(QStringLiteral("-r6")))
            return true;
        return fail(QStringLiteral(
            "The Gaussian world manifest is missing environment.backgroundColorSrgb."));
    }
    if (!environmentValue.isObject())
        return fail(QStringLiteral("The Gaussian world environment must be an object."));
    const QJsonObject environmentObject = environmentValue.toObject();

    const QJsonValue backgroundValue = environmentObject.value(QStringLiteral("backgroundColorSrgb"));
    if (!backgroundValue.isArray()) {
        return fail(QStringLiteral(
            "environment.backgroundColorSrgb must be an array of three numbers."));
    }
    const QJsonArray components = backgroundValue.toArray();
    if (components.size() != 3) {
        return fail(QStringLiteral(
            "environment.backgroundColorSrgb must contain exactly three numbers."));
    }
    std::array<float, 3> backgroundValues {};
    for (int component = 0; component < 3; ++component) {
        const QJsonValue value = components.at(component);
        const double number = value.toDouble(std::numeric_limits<double>::quiet_NaN());
        if (!value.isDouble() || !std::isfinite(number) || number < 0.0 || number > 1.0) {
            return fail(QStringLiteral(
                "environment.backgroundColorSrgb values must be finite numbers within [0,1]."));
        }
        backgroundValues[size_t(component)] = float(number);
    }
    environment->backgroundColorSrgb = QVector3D(backgroundValues[0],
                                                  backgroundValues[1],
                                                  backgroundValues[2]);

    const QString directionalSource = QStringLiteral(
        "observed-oneformer-sky-equirectangular-plus-mean-fallback-srgb-v1");
    const QJsonValue descriptorValue = environmentObject.value(
        QStringLiteral("observedDirectionalEnvironment"));
    if (descriptorValue.isUndefined()) {
        if (environmentObject.value(QStringLiteral("backgroundSource")).toString()
            == directionalSource) {
            return fail(QStringLiteral(
                "The world declares directional sky evidence but its descriptor is missing."));
        }
        return true; // Historical verified worlds use their recorded constant fallback.
    }
    if (!descriptorValue.isObject()) {
        return fail(QStringLiteral("observedDirectionalEnvironment must be an object."));
    }
    const QJsonObject descriptor = descriptorValue.toObject();
    if (descriptor.value(QStringLiteral("schema")).toString()
            != QStringLiteral("servo.observed-directional-environment/v1")
        || descriptor.value(QStringLiteral("method")).toString()
               != QStringLiteral("oneformer-observed-sky-equirectangular-rgba-v1")
        || descriptor.value(QStringLiteral("projection")).toString()
               != QStringLiteral("equirectangular-atan2-x-z-y-up-v1")) {
        return fail(QStringLiteral("Observed directional sky evidence has an unsupported contract."));
    }
    if (descriptor.value(QStringLiteral("colorSpace")).toString() != QStringLiteral("srgb")
        || descriptor.value(QStringLiteral("containsGeneratedPixels")).toBool(true)
        || descriptor.value(QStringLiteral("finiteGeometry")).toBool(true)
        || descriptor.value(QStringLiteral("metric")).toBool(true)) {
        return fail(QStringLiteral("Observed directional sky evidence has unsafe provenance."));
    }
    const QString asset = descriptor.value(QStringLiteral("asset")).toString();
    if (asset != QStringLiteral("environment/observed-sky-equirectangular.png")) {
        return fail(QStringLiteral("Observed directional sky asset path is not canonical."));
    }
    const QString expectedHash = descriptor.value(QStringLiteral("assetSha256")).toString();
    const QRegularExpression sha256Pattern(QStringLiteral("^sha256:[0-9a-f]{64}$"));
    if (!sha256Pattern.match(expectedHash).hasMatch()) {
        return fail(QStringLiteral("Observed directional sky asset hash is invalid."));
    }
    const auto boundedInteger = [&descriptor](const QString &name,
                                               int minimum,
                                               int maximum,
                                               int *result) {
        const QJsonValue value = descriptor.value(name);
        const double number = value.toDouble(std::numeric_limits<double>::quiet_NaN());
        if (!value.isDouble() || !std::isfinite(number) || std::floor(number) != number
            || number < minimum || number > maximum) {
            return false;
        }
        *result = int(number);
        return true;
    };
    int width = 0;
    int height = 0;
    if (!boundedInteger(QStringLiteral("width"), 64, 8192, &width)
        || !boundedInteger(QStringLiteral("height"), 32, 4096, &height)
        || width != height * 2) {
        return fail(QStringLiteral(
            "Observed directional sky dimensions must be 2:1 within the supported range."));
    }
    const QJsonValue label = descriptor.value(QStringLiteral("sourceSkyLabel"));
    if (!label.isDouble() || label.toInt(-1) != 17) {
        return fail(QStringLiteral("Observed directional sky evidence must use the pinned sky label."));
    }

    const QString assetPath = bundleDirectory.filePath(asset);
    QFile assetFile(assetPath);
    if (!assetFile.open(QIODevice::ReadOnly)) {
        return fail(QStringLiteral("Unable to read observed directional sky asset: %1")
                        .arg(assetFile.errorString()));
    }
    QCryptographicHash digest(QCryptographicHash::Sha256);
    while (!assetFile.atEnd())
        digest.addData(assetFile.read(1024 * 1024));
    const QString actualHash = QStringLiteral("sha256:")
                                   + QString::fromLatin1(digest.result().toHex());
    assetFile.close();
    if (actualHash != expectedHash)
        return fail(QStringLiteral("Observed directional sky PNG hash does not match world.json."));

    QImage image(assetPath);
    if (image.isNull() || image.size() != QSize(width, height)) {
        return fail(QStringLiteral("Observed directional sky PNG dimensions are invalid."));
    }
    image = image.convertToFormat(QImage::Format_RGBA8888);
    for (int row = 0; row < image.height(); ++row) {
        const QRgb *pixels = reinterpret_cast<const QRgb *>(image.constScanLine(row));
        for (int column = 0; column < image.width(); ++column) {
            const QRgb pixel = pixels[column];
            if (qAlpha(pixel) != 0 && qAlpha(pixel) != 255) {
                return fail(QStringLiteral(
                    "Observed directional sky alpha must be exact observed/unobserved coverage."));
            }
            if (qAlpha(pixel) == 0
                && (qRed(pixel) != 0 || qGreen(pixel) != 0 || qBlue(pixel) != 0)) {
                return fail(QStringLiteral(
                    "Unobserved directional sky texels must have zero RGB padding."));
            }
        }
    }
    environment->observedDirectionalRgba = image;
    environment->hasObservedDirectionalEnvironment = true;
    return true;
}

bool Servo::Rendering::readGaussianWorldBackground(const QString &plyPath,
                                                    QVector3D *backgroundColorSrgb,
                                                    QString *error)
{
    if (!backgroundColorSrgb) {
        if (error)
            *error = QStringLiteral("The Gaussian background output is null.");
        return false;
    }
    GaussianWorldEnvironment environment;
    if (!readGaussianWorldEnvironment(plyPath, &environment, error))
        return false;
    *backgroundColorSrgb = environment.backgroundColorSrgb;
    return true;
}

QColor Servo::Rendering::gaussianAccumulationClearColor(
    const QVector3D &backgroundColorSrgb,
    int visualizationMode)
{
    Q_UNUSED(backgroundColorSrgb);
    // Keep transmittance in the alpha target.  Appearance is composited over
    // the recorded directional/constant environment once, in the presentation
    // pass.  Clearing this pass to a colour would bake an incorrect fallback
    // behind every low-opacity splat and make the final composition impossible.
    if (visualizationMode != 0)
        return QColor::fromRgbF(0.0f, 0.0f, 0.0f, 1.0f);
    return QColor::fromRgbF(0.0f, 0.0f, 0.0f, 0.0f);
}

class GaussianSplatRenderer final : public QQuickRhiItemRenderer
{
public:
    ~GaussianSplatRenderer() override = default;
    void initialize(QRhiCommandBuffer *commandBuffer) override;
    void synchronize(QQuickRhiItem *item) override;
    void render(QRhiCommandBuffer *commandBuffer) override;

private:
    void resetResources();
    bool createSceneResources(QRhiCommandBuffer *commandBuffer);
    bool ensureRenderResources(const QSize &outputSize);
    void reportStats(double frameMilliseconds,
                     double gpuMilliseconds,
                     double sortMilliseconds);

    QRhi *m_rhi = nullptr;
    QRhiRenderPassDescriptor *m_renderPassDescriptor = nullptr;
    std::unique_ptr<QRhiBuffer> m_splatBuffer;
    std::unique_ptr<QRhiBuffer> m_projectedBuffer;
    std::array<std::unique_ptr<QRhiBuffer>, 2> m_depthKeyBuffers;
    std::array<std::unique_ptr<QRhiBuffer>, 2> m_orderBuffers;
    std::unique_ptr<QRhiBuffer> m_groupHistogramBuffer;
    std::unique_ptr<QRhiBuffer> m_groupPrefixBuffer;
    std::unique_ptr<QRhiBuffer> m_digitTotalsBuffer;
    std::unique_ptr<QRhiBuffer> m_digitBasesBuffer;
    std::unique_ptr<QRhiBuffer> m_radixConfigBuffer;
    std::unique_ptr<QRhiBuffer> m_uniformBuffer;
    std::unique_ptr<QRhiShaderResourceBindings> m_bindings;
    std::unique_ptr<QRhiShaderResourceBindings> m_preprocessBindings;
    std::array<std::unique_ptr<QRhiShaderResourceBindings>, kRadixPassCount>
        m_histogramBindings;
    std::array<std::unique_ptr<QRhiShaderResourceBindings>, kRadixPassCount>
        m_prefixBindings;
    std::array<std::unique_ptr<QRhiShaderResourceBindings>, kRadixPassCount>
        m_digitPrefixBindings;
    std::array<std::unique_ptr<QRhiShaderResourceBindings>, kRadixPassCount>
        m_scatterBindings;
    std::unique_ptr<QRhiGraphicsPipeline> m_pipeline;
    std::unique_ptr<QRhiComputePipeline> m_preprocessPipeline;
    std::unique_ptr<QRhiComputePipeline> m_histogramPipeline;
    std::unique_ptr<QRhiComputePipeline> m_prefixPipeline;
    std::unique_ptr<QRhiComputePipeline> m_digitPrefixPipeline;
    std::unique_ptr<QRhiComputePipeline> m_scatterPipeline;
    std::unique_ptr<QRhiTexture> m_hdrTexture;
    std::unique_ptr<QRhiTextureRenderTarget> m_hdrRenderTarget;
    std::unique_ptr<QRhiRenderPassDescriptor> m_hdrRenderPassDescriptor;
    std::unique_ptr<QRhiTexture> m_environmentTexture;
    std::unique_ptr<QRhiSampler> m_presentSampler;
    std::unique_ptr<QRhiShaderResourceBindings> m_presentBindings;
    std::unique_ptr<QRhiGraphicsPipeline> m_presentPipeline;
    std::shared_ptr<const GaussianSceneData> m_scene;
    std::shared_ptr<const GaussianSceneData> m_uploadedScene;
    QPointer<GaussianSplatView> m_item;
    QVector3D m_cameraPosition;
    QVector3D m_cameraForward;
    QVector3D m_cameraUp;
    float m_verticalFov = 52.0f;
    int m_visualizationMode = 0;
    quint64 m_cameraRevision = 0;
    quint64 m_sortedCameraRevision = 0;
    QSize m_renderResourceSize;
    quint32 m_computeWorkgroupCount = 0;
    quint32 m_radixConfigStride = 0;
    int m_visibleCount = 0;
    double m_lastSortMilliseconds = 0.0;
    QElapsedTimer m_reportTimer;
    QElapsedTimer m_frameTimer;
    int m_framesSinceReport = 0;
    int m_orderUpdatesSinceReport = 0;
};

GaussianSplatView::GaussianSplatView(QQuickItem *parent)
    : QQuickRhiItem(parent)
{
    setSampleCount(1);
    setAlphaBlending(false);
    // The renderer owns an internal RGBA16F accumulation target.  The item
    // itself is display-referred RGBA8 after the explicit presentation pass;
    // exposing the HDR texture to Qt Quick makes Qt apply a linear-to-display
    // transfer to already display-referred 3DGS colors and washes the scene out.
    setColorBufferFormat(TextureFormat::RGBA8);
    setFlag(ItemHasContents, true);
    setAcceptedMouseButtons(Qt::AllButtons);
}

GaussianSplatView::~GaussianSplatView() = default;

QUrl GaussianSplatView::source() const { return m_source; }
bool GaussianSplatView::loading() const { return m_loading; }
bool GaussianSplatView::ready() const { return bool(m_scene); }
QString GaussianSplatView::statusText() const { return m_statusText; }
QString GaussianSplatView::errorString() const { return m_errorString; }
double GaussianSplatView::loadProgress() const { return m_loadProgress; }
qint64 GaussianSplatView::gaussianCount() const { return m_scene ? m_scene->count : 0; }
int GaussianSplatView::visibleGaussianCount() const { return m_visibleGaussianCount; }
double GaussianSplatView::renderFps() const { return m_renderFps; }
double GaussianSplatView::frameTimeMs() const { return m_frameTimeMs; }
double GaussianSplatView::gpuTimeMs() const { return m_gpuTimeMs; }
double GaussianSplatView::sortTimeMs() const { return m_sortTimeMs; }
double GaussianSplatView::geometryUpdateFps() const { return m_geometryUpdateFps; }
int GaussianSplatView::cameraRevisionLag() const { return m_cameraRevisionLag; }
double GaussianSplatView::movementSpeed() const { return m_movementSpeed; }
bool GaussianSplatView::pathAvailable() const
{
    return m_scene && m_scene->cameraPathDistances.size() >= 2;
}
bool GaussianSplatView::followPath() const { return m_followPath && pathAvailable(); }
double GaussianSplatView::pathProgress() const
{
    if (!pathAvailable() || m_scene->cameraPathDistances.last() <= 1e-8f)
        return 0.0;
    return std::clamp(m_pathDistance / double(m_scene->cameraPathDistances.last()), 0.0, 1.0);
}
int GaussianSplatView::visualizationMode() const { return m_visualizationMode; }

void GaussianSplatView::setSource(const QUrl &source)
{
    if (m_source == source)
        return;
    m_source = source;
    emit sourceChanged();
    const QString path = source.isLocalFile() ? source.toLocalFile() : source.toString();
    if (path.isEmpty())
        clearScene();
    else
        loadSource(path);
}

void GaussianSplatView::setMovementSpeed(double value)
{
    const double bounded = std::clamp(value, 0.01, 20.0);
    if (qFuzzyCompare(m_movementSpeed, bounded))
        return;
    m_movementSpeed = bounded;
    emit movementSpeedChanged();
}

void GaussianSplatView::setFollowPath(bool value)
{
    const bool bounded = value && pathAvailable();
    if (m_followPath == bounded)
        return;
    m_followPath = bounded;
    if (m_followPath) {
        m_pathDistance = 0.0;
        m_pathLateralOffset = 0.0;
        m_pathVerticalOffset = 0.0;
        updatePathCamera();
        ++m_cameraRevision;
        emit pathProgressChanged();
        update();
    }
    emit navigationModeChanged();
}

void GaussianSplatView::setVisualizationMode(int value)
{
    const int bounded = std::clamp(value, 0, 3);
    if (m_visualizationMode == bounded)
        return;
    m_visualizationMode = bounded;
    emit visualizationModeChanged();
    update();
}

void GaussianSplatView::resetCamera()
{
    if (m_scene) {
        m_cameraPosition = m_initialPosition;
        m_verticalFieldOfView = m_scene->verticalFov;
        m_pitch = 0.0f;
        m_yaw = 0.0f;
        m_pathDistance = 0.0;
        m_pathLateralOffset = 0.0;
        m_pathVerticalOffset = 0.0;
        m_baseForward = m_initialForward;
        m_baseUp = m_initialUp;
        if (followPath())
            updatePathCamera();
        else
            updateCameraVectors();
        ++m_cameraRevision;
        emit pathProgressChanged();
        update();
    }
}

void GaussianSplatView::look(double deltaX, double deltaY)
{
    if (!m_scene)
        return;
    constexpr float sensitivity = 0.0032f;
    constexpr float maximumPitch = 1.48353f; // 85 degrees: never crosses the horizon pole.
    const QVector3D worldUp = normalizedOr(m_navigationUp, m_initialUp);
    const float basePitch = std::asin(std::clamp(
        QVector3D::dotProduct(normalizedOr(m_initialForward, QVector3D(0, 0, -1)),
                              worldUp),
        -1.0f,
        1.0f));
    m_yaw -= float(deltaX) * sensitivity;
    const float totalPitch = std::clamp(basePitch + m_pitch
                                            - float(deltaY) * sensitivity,
                                        -maximumPitch,
                                        maximumPitch);
    m_pitch = totalPitch - basePitch;
    updateCameraVectors();
    ++m_cameraRevision;
    update();
}

void GaussianSplatView::moveCamera(double forward,
                                   double right,
                                   double up,
                                   double elapsedSeconds)
{
    if (!m_scene || elapsedSeconds <= 0.0)
        return;
    if (followPath()) {
        const double travel = m_movementSpeed * elapsedSeconds;
        const double maximumDistance = m_scene->cameraPathDistances.last();
        const double previousDistance = m_pathDistance;
        m_pathDistance = std::clamp(m_pathDistance + forward * travel,
                                    0.0,
                                    maximumDistance);
        const double limit = m_scene->pathOffsetLimit;
        m_pathLateralOffset = std::clamp(m_pathLateralOffset + right * travel,
                                         -limit,
                                         limit);
        m_pathVerticalOffset = std::clamp(m_pathVerticalOffset + up * travel,
                                          -limit,
                                          limit);
        if (qFuzzyCompare(previousDistance, m_pathDistance)
            && qFuzzyIsNull(right) && qFuzzyIsNull(up)) {
            return;
        }
        updatePathCamera();
        ++m_cameraRevision;
        emit pathProgressChanged();
        update();
        return;
    }
    const QVector3D worldUp = normalizedOr(m_navigationUp, m_initialUp);
    QVector3D flatForward = m_cameraForward
                            - worldUp * QVector3D::dotProduct(m_cameraForward, worldUp);
    flatForward = normalizedOr(flatForward, m_cameraForward);
    const QVector3D flatRight = normalizedOr(QVector3D::crossProduct(flatForward,
                                                                     worldUp),
                                              QVector3D(1, 0, 0));
    QVector3D direction = flatForward * float(forward) + flatRight * float(right)
                          + worldUp * float(up);
    if (direction.lengthSquared() <= 1e-8f)
        return;
    direction.normalize();
    m_cameraPosition += direction * float(m_movementSpeed * elapsedSeconds);
    ++m_cameraRevision;
    update();
}

void GaussianSplatView::changeMovementSpeed(double wheelSteps)
{
    setMovementSpeed(m_movementSpeed * std::pow(1.18, wheelSteps));
}

QQuickRhiItemRenderer *GaussianSplatView::createRenderer()
{
    return new GaussianSplatRenderer;
}

std::shared_ptr<const GaussianSceneData> GaussianSplatView::sceneData() const { return m_scene; }
QVector3D GaussianSplatView::cameraPosition() const { return m_cameraPosition; }
QVector3D GaussianSplatView::cameraForward() const { return m_cameraForward; }
QVector3D GaussianSplatView::cameraUp() const { return m_cameraUp; }
float GaussianSplatView::verticalFieldOfView() const { return m_verticalFieldOfView; }
quint64 GaussianSplatView::cameraRevision() const { return m_cameraRevision; }

void GaussianSplatView::loadSource(const QString &path)
{
    const quint64 generation = ++m_loadGeneration;
    m_loading = true;
    m_loadProgress = 0.0;
    m_scene.reset();
    m_visibleGaussianCount = 0;
    setStatus(QStringLiteral("Reading and validating the Gaussian world"));
    emit loadingChanged();
    emit loadProgressChanged();
    emit sceneChanged();
    update();

    auto *watcher = new QFutureWatcher<LoadResult>(this);
    connect(watcher, &QFutureWatcher<LoadResult>::finished, this, [this, watcher, generation]() {
        const LoadResult result = watcher->result();
        watcher->deleteLater();
        applyLoadedScene(result.scene, result.error, generation);
    });
    watcher->setFuture(QtConcurrent::run([path]() { return loadGaussianScene(path); }));
}

void GaussianSplatView::clearScene()
{
    ++m_loadGeneration;
    const bool wasLoading = m_loading;
    m_loading = false;
    m_scene.reset();
    m_loadProgress = 0.0;
    m_visibleGaussianCount = 0;
    setStatus(QStringLiteral("No Gaussian world loaded"));
    if (wasLoading)
        emit loadingChanged();
    emit loadProgressChanged();
    emit sceneChanged();
    emit renderStatsChanged();
    update();
}

void GaussianSplatView::applyLoadedScene(std::shared_ptr<const GaussianSceneData> scene,
                                         const QString &error,
                                         quint64 generation)
{
    if (generation != m_loadGeneration)
        return;
    m_loading = false;
    m_scene = std::move(scene);
    m_loadProgress = m_scene ? 1.0 : 0.0;
    if (m_scene) {
        m_initialPosition = m_scene->initialPosition;
        m_initialForward = normalizedOr(m_scene->initialForward, QVector3D(0, 0, -1));
        m_initialUp = normalizedOr(m_scene->initialUp, QVector3D(0, 1, 0));
        m_navigationUp = normalizedOr(m_scene->navigationUp, m_initialUp);
        m_baseForward = m_initialForward;
        m_baseUp = m_initialUp;
        m_followPath = pathAvailable();
        m_verticalFieldOfView = m_scene->verticalFov;
        setMovementSpeed(m_scene->movementSpeed);
        resetCamera();
        setStatus(QStringLiteral("%1 Gaussian splats loaded").arg(m_scene->count));
    } else {
        setStatus(QStringLiteral("Unable to explore this world"), error);
    }
    emit loadingChanged();
    emit loadProgressChanged();
    emit sceneChanged();
    emit navigationModeChanged();
    update();
}

void GaussianSplatView::reportRenderStats(int visibleCount,
                                          double frameTime,
                                          double gpuTime,
                                          double sortTime,
                                          double framesPerSecond,
                                          double geometryUpdatesPerSecond,
                                          int cameraRevisionLag)
{
    m_visibleGaussianCount = visibleCount;
    m_frameTimeMs = frameTime;
    m_gpuTimeMs = gpuTime;
    m_sortTimeMs = sortTime;
    m_renderFps = framesPerSecond;
    m_geometryUpdateFps = geometryUpdatesPerSecond;
    m_cameraRevisionLag = cameraRevisionLag;
    emit renderStatsChanged();
}

void GaussianSplatView::setStatus(const QString &status, const QString &error)
{
    if (m_statusText == status && m_errorString == error)
        return;
    m_statusText = status;
    m_errorString = error;
    emit statusChanged();
}

void GaussianSplatView::updateCameraVectors()
{
    const QVector3D worldUp = normalizedOr(m_navigationUp, m_initialUp);
    const QVector3D initialForward = normalizedOr(m_baseForward, m_initialForward);
    const float basePitch = std::asin(std::clamp(QVector3D::dotProduct(initialForward,
                                                                       worldUp),
                                                 -1.0f,
                                                 1.0f));
    const QVector3D horizontalForward = normalizedOr(
        initialForward - worldUp * QVector3D::dotProduct(initialForward, worldUp),
        normalizedOr(QVector3D::crossProduct(m_baseUp, QVector3D(1, 0, 0)),
                     QVector3D(0, 0, -1)));
    const QQuaternion yawRotation = QQuaternion::fromAxisAndAngle(
        worldUp,
        qRadiansToDegrees(m_yaw));
    const QVector3D yawedForward = normalizedOr(yawRotation.rotatedVector(horizontalForward),
                                                horizontalForward);
    const QVector3D right = normalizedOr(QVector3D::crossProduct(yawedForward, worldUp),
                                         QVector3D(1, 0, 0));
    const float totalPitch = std::clamp(basePitch + m_pitch, -1.48353f, 1.48353f);
    m_cameraForward = normalizedOr(yawedForward * std::cos(totalPitch)
                                       + worldUp * std::sin(totalPitch),
                                   initialForward);
    // Rebuild the orthonormal basis from the stable scene-up axis on every
    // update. Translation cannot change it, and mouse look cannot introduce
    // roll or cross into an upside-down camera orientation.
    m_cameraUp = normalizedOr(QVector3D::crossProduct(right, m_cameraForward),
                              worldUp);
    if (QVector3D::dotProduct(m_cameraUp, worldUp) < 0.0f)
        m_cameraUp = -m_cameraUp;
}

void GaussianSplatView::updatePathCamera()
{
    if (!pathAvailable()) {
        updateCameraVectors();
        return;
    }
    const QVector<float> &distances = m_scene->cameraPathDistances;
    const auto upper = std::upper_bound(distances.cbegin(),
                                        distances.cend(),
                                        float(m_pathDistance));
    const qsizetype rightIndex = std::clamp<qsizetype>(upper - distances.cbegin(),
                                                       1,
                                                       distances.size() - 1);
    const qsizetype leftIndex = rightIndex - 1;
    const float span = std::max(distances.at(rightIndex) - distances.at(leftIndex), 1e-8f);
    const float amount = std::clamp((float(m_pathDistance) - distances.at(leftIndex)) / span,
                                    0.0f,
                                    1.0f);
    const QVector3D pathPosition = m_scene->cameraPath.at(leftIndex)
                                   * (1.0f - amount)
                                   + m_scene->cameraPath.at(rightIndex) * amount;
    const QVector3D leftForward = m_scene->cameraPathForwards.at(leftIndex);
    const QVector3D rightForward = m_scene->cameraPathForwards.at(rightIndex);
    m_baseForward = normalizedOr(leftForward * (1.0f - amount) + rightForward * amount,
                                 m_initialForward);
    m_baseUp = m_navigationUp;
    const QVector3D worldUp = normalizedOr(m_navigationUp, m_initialUp);
    QVector3D groundForward = m_baseForward
                              - worldUp * QVector3D::dotProduct(m_baseForward, worldUp);
    groundForward = normalizedOr(groundForward, m_baseForward);
    const QVector3D pathRight = normalizedOr(QVector3D::crossProduct(groundForward, worldUp),
                                              QVector3D(1, 0, 0));
    m_cameraPosition = pathPosition + pathRight * float(m_pathLateralOffset)
                       + worldUp * float(m_pathVerticalOffset);
    updateCameraVectors();
}

void GaussianSplatRenderer::resetResources()
{
    m_scatterPipeline.reset();
    m_digitPrefixPipeline.reset();
    m_prefixPipeline.reset();
    m_histogramPipeline.reset();
    m_preprocessPipeline.reset();
    m_presentPipeline.reset();
    m_presentBindings.reset();
    m_presentSampler.reset();
    m_pipeline.reset();
    m_bindings.reset();
    m_preprocessBindings.reset();
    for (auto &bindings : m_histogramBindings)
        bindings.reset();
    for (auto &bindings : m_prefixBindings)
        bindings.reset();
    for (auto &bindings : m_digitPrefixBindings)
        bindings.reset();
    for (auto &bindings : m_scatterBindings)
        bindings.reset();
    m_hdrRenderTarget.reset();
    m_hdrRenderPassDescriptor.reset();
    m_hdrTexture.reset();
    m_environmentTexture.reset();
    m_uniformBuffer.reset();
    m_radixConfigBuffer.reset();
    m_digitBasesBuffer.reset();
    m_digitTotalsBuffer.reset();
    m_groupPrefixBuffer.reset();
    m_groupHistogramBuffer.reset();
    for (auto &buffer : m_orderBuffers)
        buffer.reset();
    for (auto &buffer : m_depthKeyBuffers)
        buffer.reset();
    m_projectedBuffer.reset();
    m_splatBuffer.reset();
    m_uploadedScene.reset();
    m_visibleCount = 0;
    m_lastSortMilliseconds = 0.0;
    m_orderUpdatesSinceReport = 0;
    m_computeWorkgroupCount = 0;
    m_radixConfigStride = 0;
    m_renderResourceSize = {};
    m_renderPassDescriptor = nullptr;
}

void GaussianSplatRenderer::initialize(QRhiCommandBuffer *commandBuffer)
{
    Q_UNUSED(commandBuffer);
    if (m_rhi != rhi()) {
        resetResources();
        m_rhi = rhi();
    }
    if (m_renderPassDescriptor != renderTarget()->renderPassDescriptor()) {
        m_presentPipeline.reset();
        m_renderPassDescriptor = renderTarget()->renderPassDescriptor();
    }
}

void GaussianSplatRenderer::synchronize(QQuickRhiItem *item)
{
    auto *view = static_cast<GaussianSplatView *>(item);
    m_item = view;
    const std::shared_ptr<const GaussianSceneData> nextScene = view->sceneData();
    if (m_scene != nextScene) {
        m_scene = nextScene;
        m_sortedCameraRevision = 0;
    }
    m_cameraPosition = view->cameraPosition();
    m_cameraForward = view->cameraForward();
    m_cameraUp = view->cameraUp();
    m_verticalFov = view->verticalFieldOfView();
    m_visualizationMode = view->visualizationMode();
    m_cameraRevision = view->cameraRevision();
}

bool GaussianSplatRenderer::createSceneResources(QRhiCommandBuffer *commandBuffer)
{
    resetResources();
    m_renderPassDescriptor = renderTarget()->renderPassDescriptor();
    if (!m_scene || !m_rhi)
        return false;
    const quint64 count = quint64(m_scene->count);
    m_computeWorkgroupCount = quint32(
        (count + kComputeGroupSize - 1) / kComputeGroupSize);
    const quint64 projectedBytes = count * 4u * 4u * sizeof(float);
    const quint64 scalarBytes = count * sizeof(quint32);
    const quint64 groupedBytes = quint64(m_computeWorkgroupCount)
                                 * 256u * sizeof(quint32);
    if (m_scene->payload.size() > std::numeric_limits<quint32>::max()
        || projectedBytes > std::numeric_limits<quint32>::max()
        || scalarBytes > std::numeric_limits<quint32>::max()
        || groupedBytes > std::numeric_limits<quint32>::max()) {
        return false;
    }

    // A 1x1 transparent image keeps the presentation bindings stable for
    // standalone and legacy worlds.  It samples the recorded mean/black
    // fallback rather than inventing a directional sky texture.
    QImage environmentImage = m_scene->observedDirectionalEnvironment;
    if (environmentImage.isNull()) {
        environmentImage = QImage(1, 1, QImage::Format_RGBA8888);
        environmentImage.fill(Qt::transparent);
    } else {
        environmentImage = environmentImage.convertToFormat(QImage::Format_RGBA8888);
    }

    m_splatBuffer.reset(m_rhi->newBuffer(QRhiBuffer::Immutable,
                                          QRhiBuffer::StorageBuffer,
                                          quint32(m_scene->payload.size())));
    m_projectedBuffer.reset(m_rhi->newBuffer(QRhiBuffer::Static,
                                              QRhiBuffer::StorageBuffer,
                                              quint32(projectedBytes)));
    for (int index = 0; index < 2; ++index) {
        m_depthKeyBuffers[index].reset(m_rhi->newBuffer(QRhiBuffer::Static,
                                                        QRhiBuffer::StorageBuffer,
                                                        quint32(scalarBytes)));
        m_orderBuffers[index].reset(m_rhi->newBuffer(QRhiBuffer::Static,
                                                     QRhiBuffer::StorageBuffer,
                                                     quint32(scalarBytes)));
    }
    m_groupHistogramBuffer.reset(m_rhi->newBuffer(QRhiBuffer::Static,
                                                   QRhiBuffer::StorageBuffer,
                                                   quint32(groupedBytes)));
    m_groupPrefixBuffer.reset(m_rhi->newBuffer(QRhiBuffer::Static,
                                                QRhiBuffer::StorageBuffer,
                                                quint32(groupedBytes)));
    m_digitTotalsBuffer.reset(m_rhi->newBuffer(QRhiBuffer::Static,
                                                QRhiBuffer::StorageBuffer,
                                                256u * sizeof(quint32)));
    m_digitBasesBuffer.reset(m_rhi->newBuffer(QRhiBuffer::Static,
                                               QRhiBuffer::StorageBuffer,
                                               256u * sizeof(quint32)));
    m_radixConfigStride = quint32(m_rhi->ubufAligned(sizeof(RadixConfig)));
    m_radixConfigBuffer.reset(m_rhi->newBuffer(
        QRhiBuffer::Dynamic,
        QRhiBuffer::UniformBuffer,
        m_radixConfigStride * kRadixPassCount));
    m_uniformBuffer.reset(m_rhi->newBuffer(QRhiBuffer::Dynamic,
                                            QRhiBuffer::UniformBuffer,
                                            sizeof(CameraUniforms)));
    m_environmentTexture.reset(m_rhi->newTexture(QRhiTexture::RGBA8,
                                                   environmentImage.size()));
    if (!m_splatBuffer->create() || !m_projectedBuffer->create()
        || !m_depthKeyBuffers[0]->create() || !m_depthKeyBuffers[1]->create()
        || !m_orderBuffers[0]->create() || !m_orderBuffers[1]->create()
        || !m_groupHistogramBuffer->create() || !m_groupPrefixBuffer->create()
        || !m_digitTotalsBuffer->create() || !m_digitBasesBuffer->create()
        || !m_radixConfigBuffer->create() || !m_uniformBuffer->create()
        || !m_environmentTexture->create()) {
        return false;
    }
    m_splatBuffer->setName("Servo Gaussian attributes");
    m_projectedBuffer->setName("Servo projected Gaussians");
    m_depthKeyBuffers[0]->setName("Servo Gaussian depth keys A");
    m_depthKeyBuffers[1]->setName("Servo Gaussian depth keys B");
    m_orderBuffers[0]->setName("Servo Gaussian depth order A");
    m_orderBuffers[1]->setName("Servo Gaussian depth order B");
    m_groupHistogramBuffer->setName("Servo radix group histogram");
    m_groupPrefixBuffer->setName("Servo radix group prefix");
    m_digitTotalsBuffer->setName("Servo radix digit totals");
    m_digitBasesBuffer->setName("Servo radix digit bases");
    m_radixConfigBuffer->setName("Servo radix configurations");
    m_uniformBuffer->setName("Servo Gaussian camera uniforms");
    m_environmentTexture->setName("Servo observed directional sky evidence");

    m_bindings.reset(m_rhi->newShaderResourceBindings());
    m_bindings->setBindings({
        QRhiShaderResourceBinding::uniformBuffer(
            0, QRhiShaderResourceBinding::VertexStage, m_uniformBuffer.get()),
        QRhiShaderResourceBinding::bufferLoad(
            1, QRhiShaderResourceBinding::VertexStage, m_projectedBuffer.get()),
        QRhiShaderResourceBinding::bufferLoad(
            2, QRhiShaderResourceBinding::VertexStage, m_orderBuffers[0].get()),
    });
    if (!m_bindings->create())
        return false;

    m_preprocessBindings.reset(m_rhi->newShaderResourceBindings());
    m_preprocessBindings->setBindings({
        QRhiShaderResourceBinding::uniformBuffer(
            0, QRhiShaderResourceBinding::ComputeStage, m_uniformBuffer.get()),
        QRhiShaderResourceBinding::bufferLoad(
            1, QRhiShaderResourceBinding::ComputeStage, m_splatBuffer.get()),
        QRhiShaderResourceBinding::bufferStore(
            2, QRhiShaderResourceBinding::ComputeStage, m_projectedBuffer.get()),
        QRhiShaderResourceBinding::bufferStore(
            3, QRhiShaderResourceBinding::ComputeStage, m_depthKeyBuffers[0].get()),
        QRhiShaderResourceBinding::bufferStore(
            4, QRhiShaderResourceBinding::ComputeStage, m_orderBuffers[0].get()),
    });
    if (!m_preprocessBindings->create())
        return false;

    for (quint32 pass = 0; pass < kRadixPassCount; ++pass) {
        const int input = int(pass % 2u);
        const int output = 1 - input;
        const quint32 configOffset = pass * m_radixConfigStride;
        m_histogramBindings[pass].reset(m_rhi->newShaderResourceBindings());
        m_histogramBindings[pass]->setBindings({
            QRhiShaderResourceBinding::uniformBuffer(
                0,
                QRhiShaderResourceBinding::ComputeStage,
                m_radixConfigBuffer.get(),
                configOffset,
                sizeof(RadixConfig)),
            QRhiShaderResourceBinding::bufferLoad(
                1,
                QRhiShaderResourceBinding::ComputeStage,
                m_depthKeyBuffers[input].get()),
            QRhiShaderResourceBinding::bufferStore(
                2,
                QRhiShaderResourceBinding::ComputeStage,
                m_groupHistogramBuffer.get()),
        });
        m_prefixBindings[pass].reset(m_rhi->newShaderResourceBindings());
        m_prefixBindings[pass]->setBindings({
            QRhiShaderResourceBinding::uniformBuffer(
                0,
                QRhiShaderResourceBinding::ComputeStage,
                m_radixConfigBuffer.get(),
                configOffset,
                sizeof(RadixConfig)),
            QRhiShaderResourceBinding::bufferLoad(
                1,
                QRhiShaderResourceBinding::ComputeStage,
                m_groupHistogramBuffer.get()),
            QRhiShaderResourceBinding::bufferStore(
                2,
                QRhiShaderResourceBinding::ComputeStage,
                m_groupPrefixBuffer.get()),
            QRhiShaderResourceBinding::bufferStore(
                3,
                QRhiShaderResourceBinding::ComputeStage,
                m_digitTotalsBuffer.get()),
        });
        m_digitPrefixBindings[pass].reset(m_rhi->newShaderResourceBindings());
        m_digitPrefixBindings[pass]->setBindings({
            QRhiShaderResourceBinding::bufferLoad(
                0,
                QRhiShaderResourceBinding::ComputeStage,
                m_digitTotalsBuffer.get()),
            QRhiShaderResourceBinding::bufferStore(
                1,
                QRhiShaderResourceBinding::ComputeStage,
                m_digitBasesBuffer.get()),
        });
        m_scatterBindings[pass].reset(m_rhi->newShaderResourceBindings());
        m_scatterBindings[pass]->setBindings({
            QRhiShaderResourceBinding::uniformBuffer(
                0,
                QRhiShaderResourceBinding::ComputeStage,
                m_radixConfigBuffer.get(),
                configOffset,
                sizeof(RadixConfig)),
            QRhiShaderResourceBinding::bufferLoad(
                1,
                QRhiShaderResourceBinding::ComputeStage,
                m_depthKeyBuffers[input].get()),
            QRhiShaderResourceBinding::bufferLoad(
                2,
                QRhiShaderResourceBinding::ComputeStage,
                m_orderBuffers[input].get()),
            QRhiShaderResourceBinding::bufferStore(
                3,
                QRhiShaderResourceBinding::ComputeStage,
                m_depthKeyBuffers[output].get()),
            QRhiShaderResourceBinding::bufferStore(
                4,
                QRhiShaderResourceBinding::ComputeStage,
                m_orderBuffers[output].get()),
            QRhiShaderResourceBinding::bufferLoad(
                5,
                QRhiShaderResourceBinding::ComputeStage,
                m_groupPrefixBuffer.get()),
            QRhiShaderResourceBinding::bufferLoad(
                6,
                QRhiShaderResourceBinding::ComputeStage,
                m_digitBasesBuffer.get()),
        });
        if (!m_histogramBindings[pass]->create()
            || !m_prefixBindings[pass]->create()
            || !m_digitPrefixBindings[pass]->create()
            || !m_scatterBindings[pass]->create()) {
            return false;
        }
    }

    const QShader preprocessShader = loadShader(
        QStringLiteral(":/servo/rendering/shaders/gaussian_preprocess.comp.qsb"));
    const QShader histogramShader = loadShader(
        QStringLiteral(":/servo/rendering/shaders/gaussian_radix_histogram.comp.qsb"));
    const QShader prefixShader = loadShader(
        QStringLiteral(":/servo/rendering/shaders/gaussian_radix_prefix.comp.qsb"));
    const QShader digitPrefixShader = loadShader(
        QStringLiteral(":/servo/rendering/shaders/gaussian_radix_digit_prefix.comp.qsb"));
    const QShader scatterShader = loadShader(
        QStringLiteral(":/servo/rendering/shaders/gaussian_radix_scatter.comp.qsb"));
    if (!preprocessShader.isValid() || !histogramShader.isValid()
        || !prefixShader.isValid() || !digitPrefixShader.isValid()
        || !scatterShader.isValid()) {
        return false;
    }
    const auto createComputePipeline = [this](
                                           std::unique_ptr<QRhiComputePipeline> &pipeline,
                                           const QShader &shader,
                                           QRhiShaderResourceBindings *bindings) {
        pipeline.reset(m_rhi->newComputePipeline());
        pipeline->setShaderStage({ QRhiShaderStage::Compute, shader });
        pipeline->setShaderResourceBindings(bindings);
        return pipeline->create();
    };
    if (!createComputePipeline(m_preprocessPipeline,
                               preprocessShader,
                               m_preprocessBindings.get())
        || !createComputePipeline(m_histogramPipeline,
                                  histogramShader,
                                  m_histogramBindings[0].get())
        || !createComputePipeline(m_prefixPipeline,
                                  prefixShader,
                                  m_prefixBindings[0].get())
        || !createComputePipeline(m_digitPrefixPipeline,
                                  digitPrefixShader,
                                  m_digitPrefixBindings[0].get())
        || !createComputePipeline(m_scatterPipeline,
                                  scatterShader,
                                  m_scatterBindings[0].get())) {
        return false;
    }

    QRhiResourceUpdateBatch *updates = m_rhi->nextResourceUpdateBatch();
    updates->uploadStaticBuffer(m_splatBuffer.get(), m_scene->payload);
    updates->uploadTexture(m_environmentTexture.get(), environmentImage);
    for (quint32 pass = 0; pass < kRadixPassCount; ++pass) {
        const RadixConfig config { quint32(m_scene->count),
                                   m_computeWorkgroupCount,
                                   pass * 8u,
                                   0u };
        updates->updateDynamicBuffer(m_radixConfigBuffer.get(),
                                     pass * m_radixConfigStride,
                                     sizeof(config),
                                     &config);
    }
    commandBuffer->resourceUpdate(updates);
    m_uploadedScene = m_scene;
    m_sortedCameraRevision = 0;
    m_visibleCount = m_scene->count;
    return true;
}

bool GaussianSplatRenderer::ensureRenderResources(const QSize &outputSize)
{
    if (!m_rhi || outputSize.isEmpty() || !m_bindings || !m_renderPassDescriptor)
        return false;
    if (m_renderResourceSize == outputSize && m_hdrTexture && m_hdrRenderTarget
        && m_hdrRenderPassDescriptor && m_environmentTexture && m_pipeline && m_presentPipeline) {
        return true;
    }

    // The Gaussian pass must retain HDR values until every translucent
    // contributor has blended.  A second presentation pass performs the one
    // and only display clamp; this matches gsplat while avoiding a washed-out
    // Qt Quick conversion of an unclamped RGBA16F item.
    m_presentPipeline.reset();
    m_presentBindings.reset();
    m_presentSampler.reset();
    m_pipeline.reset();
    m_hdrRenderTarget.reset();
    m_hdrRenderPassDescriptor.reset();
    m_hdrTexture.reset();
    m_renderResourceSize = {};

    m_hdrTexture.reset(m_rhi->newTexture(QRhiTexture::RGBA16F,
                                          outputSize,
                                          1,
                                          QRhiTexture::RenderTarget));
    if (!m_hdrTexture->create())
        return false;
    m_hdrTexture->setName("Servo Gaussian HDR accumulation");
    QRhiTextureRenderTargetDescription targetDescription(
        QRhiColorAttachment(m_hdrTexture.get()));
    m_hdrRenderTarget.reset(m_rhi->newTextureRenderTarget(targetDescription));
    m_hdrRenderPassDescriptor.reset(
        m_hdrRenderTarget->newCompatibleRenderPassDescriptor());
    m_hdrRenderTarget->setRenderPassDescriptor(m_hdrRenderPassDescriptor.get());
    if (!m_hdrRenderTarget->create())
        return false;

    const QShader gaussianVertex = loadShader(
        QStringLiteral(":/servo/rendering/shaders/gaussian.vert.qsb"));
    const QShader gaussianFragment = loadShader(
        QStringLiteral(":/servo/rendering/shaders/gaussian.frag.qsb"));
    const QShader presentVertex = loadShader(
        QStringLiteral(":/servo/rendering/shaders/gaussian_present.vert.qsb"));
    const QShader presentFragment = loadShader(
        QStringLiteral(":/servo/rendering/shaders/gaussian_present.frag.qsb"));
    if (!gaussianVertex.isValid() || !gaussianFragment.isValid()
        || !presentVertex.isValid() || !presentFragment.isValid()) {
        return false;
    }

    m_pipeline.reset(m_rhi->newGraphicsPipeline());
    m_pipeline->setShaderStages({ { QRhiShaderStage::Vertex, gaussianVertex },
                                  { QRhiShaderStage::Fragment, gaussianFragment } });
    m_pipeline->setTopology(QRhiGraphicsPipeline::Triangles);
    m_pipeline->setCullMode(QRhiGraphicsPipeline::None);
    m_pipeline->setDepthTest(false);
    m_pipeline->setDepthWrite(false);
    QRhiGraphicsPipeline::TargetBlend blend;
    blend.enable = true;
    blend.srcColor = QRhiGraphicsPipeline::One;
    blend.dstColor = QRhiGraphicsPipeline::OneMinusSrcAlpha;
    blend.srcAlpha = QRhiGraphicsPipeline::One;
    blend.dstAlpha = QRhiGraphicsPipeline::OneMinusSrcAlpha;
    m_pipeline->setTargetBlends({ blend });
    m_pipeline->setShaderResourceBindings(m_bindings.get());
    m_pipeline->setRenderPassDescriptor(m_hdrRenderPassDescriptor.get());
    if (!m_pipeline->create())
        return false;

    m_presentSampler.reset(m_rhi->newSampler(QRhiSampler::Nearest,
                                              QRhiSampler::Nearest,
                                              QRhiSampler::None,
                                              QRhiSampler::ClampToEdge,
                                              QRhiSampler::ClampToEdge,
                                              QRhiSampler::ClampToEdge));
    if (!m_presentSampler->create())
        return false;
    m_presentBindings.reset(m_rhi->newShaderResourceBindings());
    m_presentBindings->setBindings({
        QRhiShaderResourceBinding::sampledTexture(
            0,
            QRhiShaderResourceBinding::FragmentStage,
            m_hdrTexture.get(),
            m_presentSampler.get()),
        QRhiShaderResourceBinding::sampledTexture(
            1,
            QRhiShaderResourceBinding::FragmentStage,
            m_environmentTexture.get(),
            m_presentSampler.get()),
        QRhiShaderResourceBinding::uniformBuffer(
            2,
            QRhiShaderResourceBinding::FragmentStage,
            m_uniformBuffer.get()),
    });
    if (!m_presentBindings->create())
        return false;

    m_presentPipeline.reset(m_rhi->newGraphicsPipeline());
    m_presentPipeline->setShaderStages({ { QRhiShaderStage::Vertex, presentVertex },
                                         { QRhiShaderStage::Fragment, presentFragment } });
    m_presentPipeline->setTopology(QRhiGraphicsPipeline::Triangles);
    m_presentPipeline->setCullMode(QRhiGraphicsPipeline::None);
    m_presentPipeline->setDepthTest(false);
    m_presentPipeline->setDepthWrite(false);
    m_presentPipeline->setShaderResourceBindings(m_presentBindings.get());
    m_presentPipeline->setRenderPassDescriptor(m_renderPassDescriptor);
    if (!m_presentPipeline->create())
        return false;

    m_renderResourceSize = outputSize;
    return true;
}

void GaussianSplatRenderer::render(QRhiCommandBuffer *commandBuffer)
{
    QElapsedTimer frame;
    frame.start();
    if (!m_scene) {
        // Scene clearing happens on the GUI thread.  Release the previous
        // PLY, compute buffers, and directional image on the render thread
        // before presenting the empty state so a deleted world frees VRAM.
        if (m_uploadedScene)
            resetResources();
        commandBuffer->beginPass(renderTarget(), QColor(QStringLiteral("#151719")), { 1.0f, 0 });
        commandBuffer->endPass();
        return;
    }
    // A scene can become available after initialize() but before render().
    // Create its resources and continue into the populated pass in the same
    // frame; returning here leaves a static QQuickRhiItem permanently blank
    // because no later update is guaranteed.
    if (m_uploadedScene != m_scene && !createSceneResources(commandBuffer)) {
        commandBuffer->beginPass(renderTarget(), QColor(QStringLiteral("#151719")), { 1.0f, 0 });
        commandBuffer->endPass();
        return;
    }

    const QSize outputSize = renderTarget()->pixelSize();
    if (outputSize.isEmpty())
        return;
    if (!ensureRenderResources(outputSize)) {
        commandBuffer->beginPass(renderTarget(), QColor(QStringLiteral("#151719")), { 1.0f, 0 });
        commandBuffer->endPass();
        return;
    }

    QMatrix4x4 view;
    view.lookAt(m_cameraPosition,
                m_cameraPosition + normalizedOr(m_cameraForward, QVector3D(0, 0, -1)),
                normalizedOr(m_cameraUp, QVector3D(0, 1, 0)));
    QMatrix4x4 projection = m_rhi->clipSpaceCorrMatrix();
    projection.perspective(m_verticalFov,
                           float(outputSize.width()) / float(outputSize.height()),
                           kNearPlane,
                           1000.0f);
    CameraUniforms uniforms {};
    std::memcpy(uniforms.view, view.constData(), sizeof(uniforms.view));
    std::memcpy(uniforms.projection, projection.constData(), sizeof(uniforms.projection));
    uniforms.camera[0] = m_cameraPosition.x();
    uniforms.camera[1] = m_cameraPosition.y();
    uniforms.camera[2] = m_cameraPosition.z();
    uniforms.camera[3] = m_scene->visualizationFarDepth;
    const float fy = 0.5f * float(outputSize.height())
                     / std::tan(0.5f * qDegreesToRadians(m_verticalFov));
    uniforms.viewportFocal[0] = float(outputSize.width());
    uniforms.viewportFocal[1] = float(outputSize.height());
    uniforms.viewportFocal[2] = fy;
    uniforms.viewportFocal[3] = fy;
    uniforms.parameters[0] = 0.3f;
    uniforms.parameters[1] = kNearPlane;
    uniforms.parameters[2] = float(m_scene->count);
    uniforms.parameters[3] = float(m_visualizationMode);
    uniforms.environmentFallback[0] = m_scene->backgroundColorSrgb.x();
    uniforms.environmentFallback[1] = m_scene->backgroundColorSrgb.y();
    uniforms.environmentFallback[2] = m_scene->backgroundColorSrgb.z();
    uniforms.environmentFallback[3] = 1.0f;

    QRhiResourceUpdateBatch *updates = m_rhi->nextResourceUpdateBatch();
    updates->updateDynamicBuffer(m_uniformBuffer.get(), 0, sizeof(uniforms), &uniforms);

    // Projection, conservative ellipse culling, exact depth keys, and the
    // stable four-pass radix sort all use this frame's camera snapshot.  Each
    // producer/consumer transition is a separate QRhi compute pass so QRhi can
    // emit the Vulkan storage-buffer visibility barrier between usages.
    commandBuffer->beginComputePass(updates);
    commandBuffer->setComputePipeline(m_preprocessPipeline.get());
    commandBuffer->setShaderResources(m_preprocessBindings.get());
    commandBuffer->dispatch(int(m_computeWorkgroupCount), 1, 1);
    commandBuffer->endComputePass();
    for (quint32 pass = 0; pass < kRadixPassCount; ++pass) {
        commandBuffer->beginComputePass();
        commandBuffer->setComputePipeline(m_histogramPipeline.get());
        commandBuffer->setShaderResources(m_histogramBindings[pass].get());
        commandBuffer->dispatch(int(m_computeWorkgroupCount), 1, 1);
        commandBuffer->endComputePass();

        commandBuffer->beginComputePass();
        commandBuffer->setComputePipeline(m_prefixPipeline.get());
        commandBuffer->setShaderResources(m_prefixBindings[pass].get());
        commandBuffer->dispatch(1, 1, 1);
        commandBuffer->endComputePass();

        commandBuffer->beginComputePass();
        commandBuffer->setComputePipeline(m_digitPrefixPipeline.get());
        commandBuffer->setShaderResources(m_digitPrefixBindings[pass].get());
        commandBuffer->dispatch(1, 1, 1);
        commandBuffer->endComputePass();

        commandBuffer->beginComputePass();
        commandBuffer->setComputePipeline(m_scatterPipeline.get());
        commandBuffer->setShaderResources(m_scatterBindings[pass].get());
        commandBuffer->dispatch(int(m_computeWorkgroupCount), 1, 1);
        commandBuffer->endComputePass();
    }
    m_sortedCameraRevision = m_cameraRevision;
    m_visibleCount = m_scene->count;
    m_lastSortMilliseconds = 0.0;
    ++m_orderUpdatesSinceReport;

    // RGB remains premultiplied by finite-splat alpha.  The presentation pass
    // combines the remaining transmittance with only observed directional sky
    // evidence (or its explicit constant fallback), matching trainer/audit.
    commandBuffer->beginPass(m_hdrRenderTarget.get(),
                             Servo::Rendering::gaussianAccumulationClearColor(
                                 m_scene->backgroundColorSrgb,
                                 m_visualizationMode),
                             { 1.0f, 0 });
    if (m_visibleCount > 0) {
        commandBuffer->setGraphicsPipeline(m_pipeline.get());
        commandBuffer->setViewport(QRhiViewport(0,
                                                0,
                                                float(outputSize.width()),
                                                float(outputSize.height())));
        commandBuffer->setShaderResources(m_bindings.get());
        commandBuffer->draw(6, quint32(m_scene->count));
    }
    commandBuffer->endPass();
    commandBuffer->beginPass(renderTarget(), QColor(Qt::black), { 1.0f, 0 });
    commandBuffer->setGraphicsPipeline(m_presentPipeline.get());
    commandBuffer->setViewport(QRhiViewport(0,
                                            0,
                                            float(outputSize.width()),
                                            float(outputSize.height())));
    commandBuffer->setShaderResources(m_presentBindings.get());
    commandBuffer->draw(3);
    commandBuffer->endPass();
    reportStats(frame.nsecsElapsed() / 1'000'000.0,
                commandBuffer->lastCompletedGpuTime() * 1000.0,
                m_lastSortMilliseconds);
}

void GaussianSplatRenderer::reportStats(double frameMilliseconds,
                                        double gpuMilliseconds,
                                        double sortMilliseconds)
{
    if (!m_reportTimer.isValid()) {
        m_reportTimer.start();
        m_frameTimer.start();
    }
    ++m_framesSinceReport;
    if (m_reportTimer.elapsed() < 200)
        return;
    const double elapsedSeconds = m_frameTimer.nsecsElapsed() / 1'000'000'000.0;
    const double fps = elapsedSeconds > 0.0 ? m_framesSinceReport / elapsedSeconds : 0.0;
    const double geometryFps = elapsedSeconds > 0.0
                                   ? m_orderUpdatesSinceReport / elapsedSeconds
                                   : 0.0;
    const quint64 revisionLag = m_cameraRevision >= m_sortedCameraRevision
                                    ? m_cameraRevision - m_sortedCameraRevision
                                    : 0;
    const int boundedRevisionLag = int(std::min<quint64>(revisionLag,
                                                         quint64(std::numeric_limits<int>::max())));
    m_framesSinceReport = 0;
    m_orderUpdatesSinceReport = 0;
    m_reportTimer.restart();
    m_frameTimer.restart();
    const QPointer<GaussianSplatView> target = m_item;
    const int visible = m_visibleCount;
    QMetaObject::invokeMethod(
        target,
        [target,
         visible,
         frameMilliseconds,
         gpuMilliseconds,
         sortMilliseconds,
         fps,
         geometryFps,
         boundedRevisionLag]() {
            if (target)
                target->reportRenderStats(visible,
                                          frameMilliseconds,
                                          gpuMilliseconds,
                                          sortMilliseconds,
                                          fps,
                                          geometryFps,
                                          boundedRevisionLag);
        },
        Qt::QueuedConnection);
}
