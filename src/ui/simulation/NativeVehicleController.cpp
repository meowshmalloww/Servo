#include "NativeVehicleController.h"

#include <QDir>
#include <QDebug>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonValue>
#include <QUrl>
#include <QtMath>

#include <algorithm>
#include <cmath>
#include <limits>

namespace {
constexpr double fixedStepSeconds = 1.0 / 120.0;
constexpr double maximumElapsedSeconds = 0.05;
constexpr double maximumSteerDegrees = 31.0;
constexpr double tyreFriction = 1.05;
constexpr double engineForceNewtons = 8200.0;
constexpr double reverseForceNewtons = 4200.0;
constexpr double brakeForceNewtons = 14000.0;
constexpr double lateralStiffness = 8200.0;
constexpr double rollingResistance = 120.0;
constexpr double dragCoefficient = 0.48;

double finiteNumber(const QJsonObject &object, const char *name, double fallback)
{
    const double value = object.value(QLatin1String(name)).toDouble(fallback);
    return std::isfinite(value) ? value : fallback;
}

QString localPath(const QString &value)
{
    const QUrl url(value);
    return url.isLocalFile() ? url.toLocalFile() : value;
}
}

NativeVehicleController::NativeVehicleController(QObject *parent)
    : QObject(parent)
{
    m_timer.setTimerType(Qt::PreciseTimer);
    // Simulate at 120 Hz, but publish poses at the display-friendly 60 Hz
    // cadence. Updating QML and the Vulkan scene at 120 Hz forced redundant
    // frames while a route field was also being sorted and uploaded.
    m_timer.setInterval(16);
    connect(&m_timer, &QTimer::timeout, this, &NativeVehicleController::timerTick);
}

QString NativeVehicleController::status() const
{
    if (!m_ready)
        return m_errorString.isEmpty() ? QStringLiteral("No native world physics") : QStringLiteral("Physics unavailable");
    if (!m_running)
        return QStringLiteral("Ready");
    if (m_paused)
        return QStringLiteral("Paused");
    if (m_routeEnded)
        return QStringLiteral("Route safely stopped");
    if (falling())
        return QStringLiteral("Falling - no road support");
    if (grounded() && m_autoDriveEnabled)
        return m_snowAccumulation > 0.01
                   ? QStringLiteral("Auto - snow grip")
                   : QStringLiteral("Auto - 4-wheel");
    return grounded() ? QStringLiteral("Manual - 4-wheel") : QStringLiteral("Airborne");
}

double NativeVehicleController::effectiveTyreFriction() const
{
    // A packed snow surface retains 42% of the dry-road friction coefficient.
    // This affects the force budget at each wheel; it is not telemetry-only.
    return tyreFriction * (1.0 - 0.58 * std::clamp(m_snowAccumulation, 0.0, 1.0));
}

void NativeVehicleController::setSnowAccumulation(double value)
{
    const double bounded = std::clamp(value, 0.0, 1.0);
    if (qFuzzyCompare(1.0 + m_snowAccumulation, 1.0 + bounded))
        return;
    m_snowAccumulation = bounded;
    emit weatherChanged();
    emit stateChanged();
}

std::optional<QJsonObject> NativeVehicleController::readObject(const QString &path, QString *error)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        if (error)
            *error = QStringLiteral("Cannot open %1: %2").arg(path, file.errorString());
        return std::nullopt;
    }
    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(file.readAll(), &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
        if (error)
            *error = QStringLiteral("Malformed JSON %1: %2").arg(path, parseError.errorString());
        return std::nullopt;
    }
    return document.object();
}

QVector3D NativeVehicleController::jsonVector(const QJsonValue &value, bool *ok)
{
    const QJsonArray array = value.toArray();
    if (array.size() != 3) {
        *ok = false;
        return {};
    }
    const QVector3D result(float(array.at(0).toDouble()), float(array.at(1).toDouble()),
                           float(array.at(2).toDouble()));
    if (!qIsFinite(result.x()) || !qIsFinite(result.y()) || !qIsFinite(result.z()))
        *ok = false;
    return result;
}

QVector<double> NativeVehicleController::jsonNumbers(const QJsonValue &value, bool *ok)
{
    const QJsonArray array = value.toArray();
    QVector<double> result;
    result.reserve(array.size());
    for (const QJsonValue &entry : array) {
        const double number = entry.toDouble(qQNaN());
        if (!std::isfinite(number)) {
            *ok = false;
            return {};
        }
        result.append(number);
    }
    return result;
}

double NativeVehicleController::interpolate(const QVector<double> &xs, const QVector<double> &ys, double x)
{
    if (xs.size() != ys.size() || xs.isEmpty())
        return 0.0;
    if (x <= xs.first())
        return ys.first();
    if (x >= xs.last())
        return ys.last();
    const auto upper = std::upper_bound(xs.cbegin(), xs.cend(), x);
    const qsizetype high = std::distance(xs.cbegin(), upper);
    const qsizetype low = high - 1;
    const double amount = (x - xs.at(low)) / std::max(xs.at(high) - xs.at(low), 1.0e-12);
    return ys.at(low) * (1.0 - amount) + ys.at(high) * amount;
}

QVector3D NativeVehicleController::safeNormalized(const QVector3D &value, const QVector3D &fallback)
{
    if (value.lengthSquared() < 1.0e-12f)
        return fallback;
    return value.normalized();
}

QQuaternion NativeVehicleController::frameOrientation(const QVector3D &right, const QVector3D &up,
                                                       const QVector3D &forward)
{
    return QQuaternion::fromAxes(safeNormalized(right, QVector3D(1, 0, 0)),
                                 safeNormalized(up, QVector3D(0, 1, 0)),
                                 safeNormalized(forward, QVector3D(0, 0, 1))).normalized();
}

QQuaternion NativeVehicleController::cameraLookAt(const QVector3D &position, const QVector3D &target,
                                                   const QVector3D &upHint)
{
    const QVector3D forward = safeNormalized(target - position, QVector3D(0, 0, 1));
    const QVector3D cameraRight = safeNormalized(QVector3D::crossProduct(forward, upHint),
                                                  QVector3D(1, 0, 0));
    const QVector3D cameraUp = safeNormalized(QVector3D::crossProduct(cameraRight, forward), upHint);
    return QQuaternion::fromAxes(cameraRight, cameraUp, -forward).normalized();
}

bool NativeVehicleController::loadWorld(const QString &worldPathValue)
{
    stop();
    m_ready = false;
    m_errorString.clear();
    m_worldPath = QFileInfo(localPath(worldPathValue)).absoluteFilePath();
    const QString manifestPath = QDir(m_worldPath).filePath(QStringLiteral("world.json"));
    QString error;
    const auto manifest = readObject(manifestPath, &error);
    if (!manifest) {
        setError(error);
        return false;
    }
    m_worldId = manifest->value(QStringLiteral("worldId")).toString();
    const QJsonObject physics = manifest->value(QStringLiteral("physics")).toObject();
    if (physics.value(QStringLiteral("schema")).toString()
            != QLatin1String("servo.native-gaussian-vehicle-physics/v1")
        || !physics.value(QStringLiteral("ready")).toBool()
        || physics.value(QStringLiteral("carla")).toBool(true)) {
        setError(QStringLiteral("This world has no Servo-native road-physics binding."));
        return false;
    }
    const QString descriptorRelative = physics.value(QStringLiteral("descriptor")).toString();
    const QString descriptorPath = QDir(m_worldPath).filePath(descriptorRelative);
    if (!loadDescriptor(descriptorPath))
        return false;
    m_ready = true;
    reset();
    qInfo().noquote() << "Native world vehicle physics ready:" << m_worldId
                      << "scale" << m_metersPerWorldUnit << "m/world-unit";
    emit worldChanged();
    return true;
}

bool NativeVehicleController::loadDescriptor(const QString &descriptorPath)
{
    QString error;
    const auto descriptor = readObject(descriptorPath, &error);
    if (!descriptor) {
        setError(error);
        return false;
    }
    if (descriptor->value(QStringLiteral("schema")).toString()
        != QLatin1String("servo.native-gaussian-vehicle-physics/v1")) {
        setError(QStringLiteral("Native vehicle descriptor schema is unsupported."));
        return false;
    }
    if (descriptor->value(QStringLiteral("worldId")).toString() != m_worldId) {
        setError(QStringLiteral("Native vehicle descriptor belongs to another Gaussian world."));
        return false;
    }
    const QJsonObject scale = descriptor->value(QStringLiteral("siScale")).toObject();
    m_metersPerWorldUnit = finiteNumber(scale, "metersPerWorldUnit", 0.0);
    m_gravity = finiteNumber(*descriptor, "gravityMetersPerSecondSquared", 9.80665);
    if (!(m_metersPerWorldUnit > 0.0) || !(m_gravity > 0.0)) {
        setError(QStringLiteral("Native vehicle SI scale or gravity is invalid."));
        return false;
    }
    const QJsonObject vehicle = descriptor->value(QStringLiteral("vehicle")).toObject();
    m_vehicle.massKg = finiteNumber(vehicle, "massKg", m_vehicle.massKg);
    m_vehicle.lengthMeters = finiteNumber(vehicle, "lengthMeters", m_vehicle.lengthMeters);
    m_vehicle.widthMeters = finiteNumber(vehicle, "widthMeters", m_vehicle.widthMeters);
    m_vehicle.heightMeters = finiteNumber(vehicle, "heightMeters", m_vehicle.heightMeters);
    m_vehicle.wheelbaseMeters = finiteNumber(vehicle, "wheelbaseMeters", m_vehicle.wheelbaseMeters);
    m_vehicle.trackMeters = finiteNumber(vehicle, "trackMeters", m_vehicle.trackMeters);
    m_vehicle.wheelRadiusMeters = finiteNumber(vehicle, "wheelRadiusMeters", m_vehicle.wheelRadiusMeters);
    m_vehicle.suspensionRestMeters = finiteNumber(vehicle, "suspensionRestMeters", m_vehicle.suspensionRestMeters);
    m_vehicle.springNewtonsPerMeter = finiteNumber(vehicle, "springNewtonsPerMeter", m_vehicle.springNewtonsPerMeter);
    m_vehicle.damperNewtonSecondsPerMeter = finiteNumber(vehicle, "damperNewtonSecondsPerMeter", m_vehicle.damperNewtonSecondsPerMeter);
    const QString roadPath = QDir(QFileInfo(descriptorPath).absolutePath())
                                 .filePath(descriptor->value(QStringLiteral("roadSurface")).toString());
    return loadRoad(roadPath);
}

bool NativeVehicleController::loadRoad(const QString &roadPath)
{
    QString error;
    const auto road = readObject(roadPath, &error);
    if (!road) {
        setError(error);
        return false;
    }
    if (road->value(QStringLiteral("schema")).toString() != QLatin1String("servo.road-surface/v1")) {
        setError(QStringLiteral("Road surface schema is unsupported."));
        return false;
    }
    bool ok = true;
    const QJsonObject path = road->value(QStringLiteral("pathFrame")).toObject();
    const QJsonObject surface = road->value(QStringLiteral("surface")).toObject();
    m_road.origin = jsonVector(path.value(QStringLiteral("origin")), &ok);
    m_road.up = safeNormalized(jsonVector(path.value(QStringLiteral("up")), &ok), QVector3D(0, 1, 0));
    m_road.arcLengths = jsonNumbers(path.value(QStringLiteral("arcLengths")), &ok);
    m_road.centers.clear();
    for (const QJsonValue &entry : path.value(QStringLiteral("centers")).toArray())
        m_road.centers.append(jsonVector(entry, &ok));
    m_road.knots = jsonNumbers(surface.value(QStringLiteral("knots")), &ok);
    m_road.elevations = jsonNumbers(surface.value(QStringLiteral("elevations")), &ok);
    m_road.banks = jsonNumbers(surface.value(QStringLiteral("banks")), &ok);
    m_road.lateralMin = surface.value(QStringLiteral("lateralMin")).toDouble(qQNaN());
    m_road.lateralMax = surface.value(QStringLiteral("lateralMax")).toDouble(qQNaN());
    m_road.lateralOrigin = surface.value(QStringLiteral("lateralOrigin")).toDouble(qQNaN());
    ok = ok && m_road.centers.size() >= 2 && m_road.centers.size() == m_road.arcLengths.size()
         && m_road.knots.size() >= 2 && m_road.knots.size() == m_road.elevations.size()
         && m_road.knots.size() == m_road.banks.size()
         && std::isfinite(m_road.lateralMin) && std::isfinite(m_road.lateralMax)
         && std::isfinite(m_road.lateralOrigin) && m_road.lateralMax > m_road.lateralMin;
    if (!ok) {
        setError(QStringLiteral("Road surface arrays are malformed."));
        return false;
    }
    m_road.stationMin = std::max(m_road.arcLengths.first(), m_road.knots.first());
    m_road.stationMax = std::min(m_road.arcLengths.last(), m_road.knots.last());
    if (!(m_road.stationMax > m_road.stationMin)) {
        setError(QStringLiteral("Road surface has no finite overlap with its camera path."));
        return false;
    }
    return true;
}

QVector3D NativeVehicleController::pathPoint(double station, double lateral, double height,
                                             QVector3D *forwardOut, QVector3D *rightOut) const
{
    station = std::clamp(station, m_road.arcLengths.first(), m_road.arcLengths.last());
    const auto upper = std::upper_bound(m_road.arcLengths.cbegin(), m_road.arcLengths.cend(), station);
    qsizetype high = std::distance(m_road.arcLengths.cbegin(), upper);
    high = std::clamp<qsizetype>(high, 1, m_road.arcLengths.size() - 1);
    const qsizetype low = high - 1;
    const double amount = (station - m_road.arcLengths.at(low))
                          / std::max(m_road.arcLengths.at(high) - m_road.arcLengths.at(low), 1.0e-12);
    const QVector3D center = m_road.centers.at(low) * float(1.0 - amount)
                             + m_road.centers.at(high) * float(amount);
    QVector3D tangent = m_road.centers.at(high) - m_road.centers.at(low);
    tangent -= m_road.up * QVector3D::dotProduct(tangent, m_road.up);
    const QVector3D forward = safeNormalized(tangent, QVector3D(0, 0, 1));
    const QVector3D right = safeNormalized(QVector3D::crossProduct(m_road.up, forward), QVector3D(1, 0, 0));
    const float centerHeight = QVector3D::dotProduct(center - m_road.origin, m_road.up);
    const QVector3D horizontalCenter = center - m_road.up * centerHeight;
    if (forwardOut)
        *forwardOut = forward;
    if (rightOut)
        *rightOut = right;
    return horizontalCenter + right * float(lateral) + m_road.up * float(height);
}

QVector3D NativeVehicleController::pathCenter(double station, QVector3D *forwardOut) const
{
    station = std::clamp(station, m_road.arcLengths.first(), m_road.arcLengths.last());
    const auto upper = std::upper_bound(m_road.arcLengths.cbegin(), m_road.arcLengths.cend(), station);
    qsizetype high = std::distance(m_road.arcLengths.cbegin(), upper);
    high = std::clamp<qsizetype>(high, 1, m_road.arcLengths.size() - 1);
    const qsizetype low = high - 1;
    const double amount = (station - m_road.arcLengths.at(low))
                          / std::max(m_road.arcLengths.at(high) - m_road.arcLengths.at(low), 1.0e-12);
    const QVector3D center = m_road.centers.at(low) * float(1.0 - amount)
                             + m_road.centers.at(high) * float(amount);
    if (forwardOut) {
        *forwardOut = safeNormalized(m_road.centers.at(high) - m_road.centers.at(low),
                                     QVector3D(0, 0, 1));
    }
    return center;
}

NativeVehicleController::SurfaceSample NativeVehicleController::sampleRoad(const QVector3D &worldPosition) const
{
    SurfaceSample result;
    if (m_road.centers.size() < 2)
        return result;
    const QVector3D queryHorizontal = worldPosition
                                      - m_road.up * QVector3D::dotProduct(worldPosition - m_road.origin, m_road.up);
    double bestDistanceSquared = std::numeric_limits<double>::infinity();
    qsizetype bestSegment = 0;
    double bestAmount = 0.0;
    for (qsizetype index = 0; index + 1 < m_road.centers.size(); ++index) {
        QVector3D start = m_road.centers.at(index);
        QVector3D end = m_road.centers.at(index + 1);
        start -= m_road.up * QVector3D::dotProduct(start - m_road.origin, m_road.up);
        end -= m_road.up * QVector3D::dotProduct(end - m_road.origin, m_road.up);
        const QVector3D segment = end - start;
        const double lengthSquared = segment.lengthSquared();
        if (lengthSquared <= 1.0e-14)
            continue;
        const double amount = std::clamp(double(QVector3D::dotProduct(queryHorizontal - start, segment))
                                         / lengthSquared, 0.0, 1.0);
        const double distanceSquared = (queryHorizontal - (start + segment * float(amount))).lengthSquared();
        if (distanceSquared < bestDistanceSquared) {
            bestDistanceSquared = distanceSquared;
            bestSegment = index;
            bestAmount = amount;
        }
    }
    result.station = m_road.arcLengths.at(bestSegment) * (1.0 - bestAmount)
                     + m_road.arcLengths.at(bestSegment + 1) * bestAmount;
    QVector3D centerForward;
    QVector3D centerRight;
    const QVector3D center = pathPoint(result.station, 0.0, 0.0, &centerForward, &centerRight);
    result.lateral = QVector3D::dotProduct(queryHorizontal - center, centerRight);
    if (result.station < m_road.stationMin || result.station > m_road.stationMax
        || result.lateral < m_road.lateralMin || result.lateral > m_road.lateralMax)
        return result;
    const double elevation = interpolate(m_road.knots, m_road.elevations, result.station);
    const double bank = interpolate(m_road.knots, m_road.banks, result.station);
    const double epsilon = std::max((m_road.stationMax - m_road.stationMin) / 2000.0, 1.0e-5);
    const double before = std::max(m_road.stationMin, result.station - epsilon);
    const double after = std::min(m_road.stationMax, result.station + epsilon);
    const double beforeHeight = interpolate(m_road.knots, m_road.elevations, before);
    const double afterHeight = interpolate(m_road.knots, m_road.elevations, after);
    const double grade = (afterHeight - beforeHeight) / std::max(after - before, 1.0e-12);
    result.forward = safeNormalized(centerForward + m_road.up * float(grade), centerForward);
    result.right = safeNormalized(centerRight + m_road.up * float(bank), centerRight);
    result.normal = safeNormalized(QVector3D::crossProduct(result.forward, result.right), m_road.up);
    if (QVector3D::dotProduct(result.normal, m_road.up) < 0.0f)
        result.normal = -result.normal;
    result.point = pathPoint(result.station, result.lateral,
                             elevation + bank * (result.lateral - m_road.lateralOrigin));
    result.supported = true;
    return result;
}

void NativeVehicleController::start()
{
    if (!m_ready)
        return;
    if (!m_running)
        reset();
    m_running = true;
    m_paused = false;
    m_accumulator = 0.0;
    m_clock.restart();
    m_timer.start();
    emit stateChanged();
}

void NativeVehicleController::pause()
{
    if (!m_running || m_paused)
        return;
    m_paused = true;
    clearInputs();
    emit stateChanged();
}

void NativeVehicleController::resume()
{
    if (!m_running || !m_paused)
        return;
    m_paused = false;
    m_clock.restart();
    emit stateChanged();
}

void NativeVehicleController::stop()
{
    if (!m_running && !m_timer.isActive())
        return;
    m_running = false;
    m_paused = false;
    m_timer.stop();
    clearInputs();
    emit stateChanged();
}

void NativeVehicleController::reset()
{
    if (!m_ready)
        return;
    const bool wasRunning = m_running;
    const double station = m_road.stationMin + (m_road.stationMax - m_road.stationMin) * 0.015;
    const double lateral = std::clamp(m_road.lateralOrigin, m_road.lateralMin, m_road.lateralMax);
    const double elevation = interpolate(m_road.knots, m_road.elevations, station);
    const double bank = interpolate(m_road.knots, m_road.banks, station);
    QVector3D forward;
    QVector3D right;
    const QVector3D roadPoint = pathPoint(station, lateral,
                                          elevation + bank * (lateral - m_road.lateralOrigin),
                                          &forward, &right);
    const SurfaceSample sample = sampleRoad(roadPoint);
    const QVector3D up = sample.supported ? sample.normal : m_road.up;
    m_orientation = frameOrientation(right, up, forward);
    const double bodyClearance = m_vehicle.wheelRadiusMeters + m_vehicle.suspensionRestMeters + 0.27;
    m_position = roadPoint + up * float(bodyClearance / m_metersPerWorldUnit);
    m_velocityMps = {};
    m_angularVelocity = {};
    m_speedMps = 0.0;
    m_accelerationMps2 = 0.0;
    m_steering = 0.0;
    m_throttle = 0.0;
    m_brake = 0.0;
    m_wheelContacts = 4;
    m_frameId = 0;
    m_routeEnded = false;
    clearInputs();
    updateTelemetry(sample, 0.0);
    updateCamera();
    m_running = wasRunning;
    m_paused = false;
    m_accumulator = 0.0;
    if (wasRunning) {
        m_clock.restart();
        if (!m_timer.isActive())
            m_timer.start();
    }
    emit poseChanged();
    emit telemetryChanged();
    emit stateChanged();
}

void NativeVehicleController::dropFromHeight(double heightMeters)
{
    if (!m_ready)
        return;
    heightMeters = std::clamp(heightMeters, 1.0, 100.0);
    reset();
    start();
    m_position += m_road.up * float(heightMeters / m_metersPerWorldUnit);
    m_velocityMps = {};
    m_wheelContacts = 0;
    updateCamera();
    emit poseChanged();
    emit telemetryChanged();
}

void NativeVehicleController::setInput(const QString &input, bool pressed)
{
    const QString key = input.toLower();
    if (key == QLatin1String("forward"))
        m_forwardPressed = pressed;
    else if (key == QLatin1String("reverse"))
        m_reversePressed = pressed;
    else if (key == QLatin1String("left"))
        m_leftPressed = pressed;
    else if (key == QLatin1String("right"))
        m_rightPressed = pressed;
    else if (key == QLatin1String("brake"))
        m_brakePressed = pressed;
}

void NativeVehicleController::clearInputs()
{
    m_forwardPressed = false;
    m_reversePressed = false;
    m_leftPressed = false;
    m_rightPressed = false;
    m_brakePressed = false;
}

void NativeVehicleController::setCameraMode(int mode)
{
    mode = std::clamp(mode, 0, 4);
    if (m_cameraMode == mode)
        return;
    m_cameraMode = mode;
    updateCamera();
    emit cameraChanged();
}

void NativeVehicleController::setAutoDriveEnabled(bool enabled)
{
    if (m_autoDriveEnabled == enabled)
        return;
    m_autoDriveEnabled = enabled;
    m_routeEnded = false;
    clearInputs();
    emit stateChanged();
}

void NativeVehicleController::orbitCamera(double deltaYawDegrees, double deltaPitchDegrees)
{
    m_orbitYaw = std::fmod(m_orbitYaw + deltaYawDegrees, 360.0);
    m_orbitPitch = std::clamp(m_orbitPitch + deltaPitchDegrees, -5.0, 65.0);
    if (m_cameraMode == 3) {
        updateCamera();
        emit cameraChanged();
    }
}

void NativeVehicleController::timerTick()
{
    if (!m_running)
        return;
    const double elapsed = std::min(m_clock.restart() / 1000.0, maximumElapsedSeconds);
    if (m_paused)
        return;
    m_accumulator += elapsed;
    int substeps = 0;
    while (m_accumulator >= fixedStepSeconds && substeps < 16) {
        stepPhysics(fixedStepSeconds);
        m_accumulator -= fixedStepSeconds;
        ++substeps;
    }
    if (substeps > 0) {
        if (m_routeEnded && std::abs(m_speedMps) < 0.05) {
            m_velocityMps = {};
            m_angularVelocity = {};
            // Keep the live-drive state visible at the finite endpoint but
            // stop scheduling physics and render updates. Reset/restart will
            // explicitly reactivate the timer.
            m_timer.stop();
        }
        updateCamera();
        emit poseChanged();
        emit telemetryChanged();
        emit cameraChanged();
        emit stateChanged();
    }
}

void NativeVehicleController::updateControlState(double dt)
{
    const bool manualInput = m_forwardPressed || m_reversePressed || m_leftPressed
                             || m_rightPressed || m_brakePressed;
    double steerTarget = (m_rightPressed ? 1.0 : 0.0) - (m_leftPressed ? 1.0 : 0.0);
    double throttleTarget = m_forwardPressed ? 1.0 : (m_reversePressed ? -0.58 : 0.0);
    double brakeTarget = m_brakePressed ? 1.0 : 0.0;

    // This route follower consumes only the selected world's road descriptor.
    // It contains no map-specific coordinates or prerecorded steering.
    if (m_autoDriveEnabled && !manualInput) {
        const SurfaceSample road = sampleRoad(m_position);
        if (road.supported) {
            const double remainingMeters = std::max(
                0.0, (m_road.stationMax - road.station) * m_metersPerWorldUnit);
            constexpr double stopMarginMeters = 4.5;
            m_routeEnded = remainingMeters <= stopMarginMeters;
            if (m_routeEnded) {
                steerTarget = 0.0;
                throttleTarget = 0.0;
                brakeTarget = 1.0;
            } else {
                const double lookAheadMeters = std::clamp(5.5 + std::abs(m_speedMps) * 0.45,
                                                          5.5, 14.0);
                const double targetStation = std::min(
                    m_road.stationMax,
                    road.station + lookAheadMeters / m_metersPerWorldUnit);
                QVector3D targetForward;
                pathCenter(targetStation, &targetForward);
                const QVector3D currentForward = safeNormalized(
                    m_orientation.rotatedVector(QVector3D(0, 0, 1)), road.forward);
                targetForward = safeNormalized(
                    targetForward
                        - road.normal * QVector3D::dotProduct(targetForward, road.normal),
                    road.forward);
                const QVector3D planarForward = safeNormalized(
                    currentForward
                        - road.normal * QVector3D::dotProduct(currentForward, road.normal),
                    road.forward);
                const double headingError = std::atan2(
                    double(QVector3D::dotProduct(
                        QVector3D::crossProduct(planarForward, targetForward), road.normal)),
                    double(QVector3D::dotProduct(planarForward, targetForward)));
                const double lateralErrorMeters =
                    (road.lateral - m_road.lateralOrigin) * m_metersPerWorldUnit;
                steerTarget = std::clamp(headingError * 2.4 - lateralErrorMeters * 0.20,
                                         -1.0, 1.0);
                const double targetSpeed = std::min(
                    11.0,
                    std::sqrt(std::max(0.0, 2.0 * 2.4
                                               * (remainingMeters - stopMarginMeters))));
                const double speedError = targetSpeed - std::max(0.0, m_speedMps);
                throttleTarget = std::clamp(speedError / 3.5, 0.0, 1.0);
                brakeTarget = speedError < -0.35
                                  ? std::clamp(-speedError / 4.0, 0.0, 1.0)
                                  : 0.0;
            }
        } else {
            throttleTarget = 0.0;
            brakeTarget = 1.0;
        }
    } else if (manualInput) {
        m_routeEnded = false;
    }

    const double steerRate = steerTarget == 0.0 ? 4.8 : 3.3;
    const double steerAmount = std::clamp(steerRate * dt, 0.0, 1.0);
    m_steering += (steerTarget - m_steering) * steerAmount;
    m_throttle = throttleTarget;
    m_brake = brakeTarget;
    if (m_reversePressed && m_speedMps > 0.8) {
        m_throttle = 0.0;
        m_brake = 1.0;
    }
}

void NativeVehicleController::stepPhysics(double dt)
{
    updateControlState(dt);
    const double previousSpeed = m_speedMps;
    QVector3D totalForce = -m_road.up * float(m_vehicle.massKg * m_gravity);
    QVector3D totalTorque;
    m_wheelContacts = 0;

    const double halfTrack = m_vehicle.trackMeters * 0.5;
    const double halfWheelbase = m_vehicle.wheelbaseMeters * 0.5;
    const std::array<QVector3D, 4> wheelConnections = {
        QVector3D(float(-halfTrack), -0.27f, float(halfWheelbase)),
        QVector3D(float(halfTrack), -0.27f, float(halfWheelbase)),
        QVector3D(float(-halfTrack), -0.27f, float(-halfWheelbase)),
        QVector3D(float(halfTrack), -0.27f, float(-halfWheelbase)),
    };
    const double targetDistance = m_vehicle.wheelRadiusMeters + m_vehicle.suspensionRestMeters;
    for (int wheel = 0; wheel < 4; ++wheel) {
        const QVector3D connectionWorld = m_position
                                          + m_orientation.rotatedVector(wheelConnections.at(wheel))
                                                / float(m_metersPerWorldUnit);
        const SurfaceSample road = sampleRoad(connectionWorld);
        if (!road.supported)
            continue;
        const double distanceMeters = QVector3D::dotProduct(connectionWorld - road.point, road.normal)
                                      * m_metersPerWorldUnit;
        if (distanceMeters > targetDistance || distanceMeters < -0.75)
            continue;
        const QVector3D leverMeters = (connectionWorld - m_position) * float(m_metersPerWorldUnit);
        const QVector3D pointVelocity = m_velocityMps
                                        + QVector3D::crossProduct(m_angularVelocity, leverMeters);
        const double normalVelocity = QVector3D::dotProduct(pointVelocity, road.normal);
        const double compression = targetDistance - distanceMeters;
        double normalForce = m_vehicle.springNewtonsPerMeter * compression
                             - m_vehicle.damperNewtonSecondsPerMeter * normalVelocity;
        normalForce = std::clamp(normalForce, 0.0, m_vehicle.massKg * m_gravity * 2.5);
        if (normalForce <= 0.0)
            continue;
        ++m_wheelContacts;
        QVector3D wheelForward = road.forward;
        if (wheel < 2) {
            const QQuaternion steerRotation = QQuaternion::fromAxisAndAngle(
                road.normal, float(m_steering * maximumSteerDegrees));
            wheelForward = safeNormalized(steerRotation.rotatedVector(wheelForward), road.forward);
        }
        const QVector3D wheelRight = safeNormalized(QVector3D::crossProduct(road.normal, wheelForward),
                                                     road.right);
        const double longitudinalSpeed = QVector3D::dotProduct(pointVelocity, wheelForward);
        const double lateralSpeed = QVector3D::dotProduct(pointVelocity, wheelRight);
        double driveForce = 0.0;
        if (m_throttle > 0.0)
            driveForce = engineForceNewtons * m_throttle / 4.0;
        else if (m_throttle < 0.0)
            driveForce = reverseForceNewtons * m_throttle / 4.0;
        double braking = 0.0;
        if (m_brake > 0.0) {
            const double wheelBrakeLimit = brakeForceNewtons * m_brake / 4.0;
            braking = std::clamp(-longitudinalSpeed * 30'000.0,
                                 -wheelBrakeLimit, wheelBrakeLimit);
        }
        const double maximumTyreForce = normalForce * effectiveTyreFriction();
        const double longitudinalForce = std::clamp(driveForce + braking,
                                                    -maximumTyreForce,
                                                    maximumTyreForce);
        const double remainingLateralForce = std::sqrt(std::max(
            0.0, maximumTyreForce * maximumTyreForce
                     - longitudinalForce * longitudinalForce));
        const double lateralForce = std::clamp(-lateralSpeed * lateralStiffness,
                                               -remainingLateralForce,
                                               remainingLateralForce);
        const QVector3D force = road.normal * float(normalForce)
                                 + wheelForward * float(longitudinalForce)
                                 + wheelRight * float(lateralForce);
        totalForce += force;
        totalTorque += QVector3D::crossProduct(leverMeters, force);
    }

    const double velocityLength = m_velocityMps.length();
    if (velocityLength > 1.0e-4) {
        totalForce -= m_velocityMps.normalized()
                      * float(rollingResistance + dragCoefficient * velocityLength * velocityLength);
    }
    const QVector3D acceleration = totalForce / float(m_vehicle.massKg);
    m_velocityMps += acceleration * float(dt);
    m_position += m_velocityMps * float(dt / m_metersPerWorldUnit);

    const QVector3D inertia(float(m_vehicle.massKg * (m_vehicle.heightMeters * m_vehicle.heightMeters
                                                       + m_vehicle.lengthMeters * m_vehicle.lengthMeters) / 12.0),
                            float(m_vehicle.massKg * (m_vehicle.widthMeters * m_vehicle.widthMeters
                                                       + m_vehicle.lengthMeters * m_vehicle.lengthMeters) / 12.0),
                            float(m_vehicle.massKg * (m_vehicle.widthMeters * m_vehicle.widthMeters
                                                       + m_vehicle.heightMeters * m_vehicle.heightMeters) / 12.0));
    const QQuaternion inverseOrientation = m_orientation.conjugated();
    const QVector3D localTorque = inverseOrientation.rotatedVector(totalTorque);
    const QVector3D localAngularAcceleration(localTorque.x() / inertia.x(), localTorque.y() / inertia.y(),
                                             localTorque.z() / inertia.z());
    m_angularVelocity += m_orientation.rotatedVector(localAngularAcceleration) * float(dt);
    m_angularVelocity *= float(std::exp(-0.75 * dt));
    const float angularSpeed = std::min(m_angularVelocity.length(), 8.0f);
    if (angularSpeed > 1.0e-5f) {
        const QQuaternion delta = QQuaternion::fromAxisAndAngle(
            m_angularVelocity.normalized(), qRadiansToDegrees(angularSpeed * float(dt)));
        m_orientation = (delta * m_orientation).normalized();
    }
    const SurfaceSample bodyRoad = sampleRoad(m_position);
    updateTelemetry(bodyRoad, previousSpeed);
}

void NativeVehicleController::updateTelemetry(const SurfaceSample &bodyRoad, double previousSpeed)
{
    const QVector3D vehicleForward = m_orientation.rotatedVector(QVector3D(0, 0, 1));
    m_speedMps = QVector3D::dotProduct(m_velocityMps, vehicleForward);
    m_accelerationMps2 = (m_speedMps - previousSpeed) / fixedStepSeconds;
    if (bodyRoad.supported) {
        m_routeCompletion = std::clamp((bodyRoad.station - m_road.stationMin)
                                       / std::max(m_road.stationMax - m_road.stationMin, 1.0e-12),
                                       0.0, 1.0);
        m_lateralErrorM = (bodyRoad.lateral - m_road.lateralOrigin) * m_metersPerWorldUnit;
        m_frameId = qulonglong(std::llround(m_routeCompletion * double(m_road.centers.size() - 1)));
    }
}

void NativeVehicleController::updateCamera()
{
    const QVector3D carUp = safeNormalized(m_orientation.rotatedVector(QVector3D(0, 1, 0)), m_road.up);
    const QVector3D carRight = safeNormalized(m_orientation.rotatedVector(QVector3D(1, 0, 0)), QVector3D(1, 0, 0));
    const float invScale = float(1.0 / m_metersPerWorldUnit);
    const SurfaceSample road = sampleRoad(m_position);
    const double vehicleStation = road.supported
                                      ? road.station
                                      : m_road.stationMin
                                            + m_routeCompletion
                                                  * (m_road.stationMax - m_road.stationMin);
    QVector3D driverForward;
    m_driverCameraPosition = pathCenter(vehicleStation, &driverForward);
    m_driverCameraOrientation = cameraLookAt(
        m_driverCameraPosition,
        m_driverCameraPosition + driverForward * (15.0f * invScale),
        carUp);
    QVector3D target = m_position + carUp * (0.55f * invScale);
    if (m_cameraMode == 2) {
        m_cameraPosition = m_driverCameraPosition;
        m_cameraOrientation = m_driverCameraOrientation;
    } else if (m_cameraMode == 3) {
        const double cameraStation = std::max(
            m_road.stationMin, vehicleStation - 5.0 / m_metersPerWorldUnit);
        const QVector3D evidenceCenter = pathCenter(cameraStation);
        const float yaw = qDegreesToRadians(float(m_orbitYaw));
        const float pitch = qDegreesToRadians(float(m_orbitPitch));
        const QVector3D offset = carRight * float(std::sin(yaw) * 0.75)
                                 + carUp * float(std::sin(pitch) * 0.30);
        m_cameraPosition = evidenceCenter + offset * invScale;
    } else if (m_cameraMode == 4) {
        const double cameraStation = std::max(
            m_road.stationMin, vehicleStation - 4.5 / m_metersPerWorldUnit);
        m_cameraPosition = pathCenter(cameraStation) + carRight * (0.65f * invScale);
    } else {
        const double cameraStation = std::max(
            m_road.stationMin, vehicleStation - 8.5 / m_metersPerWorldUnit);
        m_cameraPosition = pathCenter(cameraStation) + carUp * (0.35f * invScale);
    }
    if (m_cameraMode != 2)
        m_cameraOrientation = cameraLookAt(m_cameraPosition, target, carUp);
    const QQuaternion inverseCar = m_orientation.conjugated();
    m_overlayCameraPosition = inverseCar.rotatedVector(m_cameraPosition - m_position)
                              * float(m_metersPerWorldUnit * 100.0);
    m_overlayCameraOrientation = (inverseCar * m_cameraOrientation).normalized();
}

void NativeVehicleController::setError(const QString &message)
{
    m_ready = false;
    m_errorString = message;
    qWarning().noquote() << "Native world vehicle physics unavailable:" << message;
    emit worldChanged();
}
