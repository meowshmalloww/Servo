#pragma once

#include <QElapsedTimer>
#include <QJsonObject>
#include <QObject>
#include <QQuaternion>
#include <QTimer>
#include <QVector3D>
#include <QtQml/qqmlregistration.h>

#include <array>
#include <optional>

class NativeVehicleController final : public QObject
{
    Q_OBJECT
    QML_NAMED_ELEMENT(NativeVehicleController)
    QML_SINGLETON

    Q_PROPERTY(bool ready READ ready NOTIFY worldChanged)
    Q_PROPERTY(bool running READ running NOTIFY stateChanged)
    Q_PROPERTY(bool paused READ paused NOTIFY stateChanged)
    Q_PROPERTY(bool autoDriveEnabled READ autoDriveEnabled WRITE setAutoDriveEnabled NOTIFY stateChanged)
    Q_PROPERTY(bool routeEnded READ routeEnded NOTIFY telemetryChanged)
    Q_PROPERTY(QString status READ status NOTIFY stateChanged)
    Q_PROPERTY(QString errorString READ errorString NOTIFY worldChanged)
    Q_PROPERTY(QString worldId READ worldId NOTIFY worldChanged)
    Q_PROPERTY(double speedMps READ speedMps NOTIFY telemetryChanged)
    Q_PROPERTY(double accelerationMps2 READ accelerationMps2 NOTIFY telemetryChanged)
    Q_PROPERTY(double steering READ steering NOTIFY telemetryChanged)
    Q_PROPERTY(double throttle READ throttle NOTIFY telemetryChanged)
    Q_PROPERTY(double brake READ brake NOTIFY telemetryChanged)
    Q_PROPERTY(double routeCompletion READ routeCompletion NOTIFY telemetryChanged)
    Q_PROPERTY(double lateralErrorM READ lateralErrorM NOTIFY telemetryChanged)
    Q_PROPERTY(bool grounded READ grounded NOTIFY telemetryChanged)
    Q_PROPERTY(bool falling READ falling NOTIFY telemetryChanged)
    Q_PROPERTY(int wheelContacts READ wheelContacts NOTIFY telemetryChanged)
    Q_PROPERTY(double gravityMetersPerSecondSquared READ gravityMetersPerSecondSquared NOTIFY worldChanged)
    Q_PROPERTY(double metersPerWorldUnit READ metersPerWorldUnit NOTIFY worldChanged)
    Q_PROPERTY(double bodyClearanceMeters READ bodyClearanceMeters NOTIFY worldChanged)
    Q_PROPERTY(double snowAccumulation READ snowAccumulation WRITE setSnowAccumulation NOTIFY weatherChanged)
    Q_PROPERTY(double effectiveTyreFriction READ effectiveTyreFriction NOTIFY weatherChanged)
    Q_PROPERTY(qulonglong frameId READ frameId NOTIFY telemetryChanged)
    Q_PROPERTY(QVector3D vehiclePosition READ vehiclePosition NOTIFY poseChanged)
    Q_PROPERTY(QQuaternion vehicleOrientation READ vehicleOrientation NOTIFY poseChanged)
    Q_PROPERTY(QVector3D cameraPosition READ cameraPosition NOTIFY cameraChanged)
    Q_PROPERTY(QQuaternion cameraOrientation READ cameraOrientation NOTIFY cameraChanged)
    Q_PROPERTY(QVector3D overlayCameraPosition READ overlayCameraPosition NOTIFY cameraChanged)
    Q_PROPERTY(QQuaternion overlayCameraOrientation READ overlayCameraOrientation NOTIFY cameraChanged)
    Q_PROPERTY(QVector3D driverCameraPosition READ driverCameraPosition NOTIFY cameraChanged)
    Q_PROPERTY(QQuaternion driverCameraOrientation READ driverCameraOrientation NOTIFY cameraChanged)
    Q_PROPERTY(int cameraMode READ cameraMode WRITE setCameraMode NOTIFY cameraChanged)

public:
    explicit NativeVehicleController(QObject *parent = nullptr);

    bool ready() const { return m_ready; }
    bool running() const { return m_running; }
    bool paused() const { return m_paused; }
    bool autoDriveEnabled() const { return m_autoDriveEnabled; }
    bool routeEnded() const { return m_routeEnded; }
    QString status() const;
    QString errorString() const { return m_errorString; }
    QString worldId() const { return m_worldId; }
    double speedMps() const { return m_speedMps; }
    double accelerationMps2() const { return m_accelerationMps2; }
    double steering() const { return m_steering; }
    double throttle() const { return m_throttle; }
    double brake() const { return m_brake; }
    double routeCompletion() const { return m_routeCompletion; }
    double lateralErrorM() const { return m_lateralErrorM; }
    bool grounded() const { return m_wheelContacts >= 2; }
    bool falling() const { return m_running && m_wheelContacts == 0 && QVector3D::dotProduct(m_velocityMps, m_road.up) < -0.25f; }
    int wheelContacts() const { return m_wheelContacts; }
    double gravityMetersPerSecondSquared() const { return m_gravity; }
    double metersPerWorldUnit() const { return m_metersPerWorldUnit; }
    double bodyClearanceMeters() const
    {
        return m_vehicle.wheelRadiusMeters + m_vehicle.suspensionRestMeters + 0.27;
    }
    double snowAccumulation() const { return m_snowAccumulation; }
    double effectiveTyreFriction() const;
    qulonglong frameId() const { return m_frameId; }
    QVector3D vehiclePosition() const { return m_position; }
    QQuaternion vehicleOrientation() const { return m_orientation; }
    QVector3D cameraPosition() const { return m_cameraPosition; }
    QQuaternion cameraOrientation() const { return m_cameraOrientation; }
    QVector3D overlayCameraPosition() const { return m_overlayCameraPosition; }
    QQuaternion overlayCameraOrientation() const { return m_overlayCameraOrientation; }
    QVector3D driverCameraPosition() const { return m_driverCameraPosition; }
    QQuaternion driverCameraOrientation() const { return m_driverCameraOrientation; }
    int cameraMode() const { return m_cameraMode; }

    Q_INVOKABLE bool loadWorld(const QString &worldPath);
    Q_INVOKABLE void start();
    Q_INVOKABLE void pause();
    Q_INVOKABLE void resume();
    Q_INVOKABLE void stop();
    Q_INVOKABLE void reset();
    Q_INVOKABLE void dropFromHeight(double heightMeters = 8.0);
    Q_INVOKABLE void setInput(const QString &input, bool pressed);
    Q_INVOKABLE void clearInputs();
    Q_INVOKABLE void orbitCamera(double deltaYawDegrees, double deltaPitchDegrees);
    void setAutoDriveEnabled(bool enabled);
    void setCameraMode(int mode);
    void setSnowAccumulation(double value);

signals:
    void worldChanged();
    void stateChanged();
    void telemetryChanged();
    void poseChanged();
    void cameraChanged();
    void weatherChanged();

private:
    struct RoadData {
        QVector<QVector3D> centers;
        QVector<double> arcLengths;
        QVector<double> knots;
        QVector<double> elevations;
        QVector<double> banks;
        QVector3D origin;
        QVector3D up;
        double lateralMin = 0.0;
        double lateralMax = 0.0;
        double lateralOrigin = 0.0;
        double stationMin = 0.0;
        double stationMax = 0.0;
    };

    struct SurfaceSample {
        bool supported = false;
        double station = 0.0;
        double lateral = 0.0;
        QVector3D point;
        QVector3D normal;
        QVector3D forward;
        QVector3D right;
    };

    struct VehicleSpec {
        double massKg = 1840.0;
        double lengthMeters = 4.75;
        double widthMeters = 1.92;
        double heightMeters = 1.45;
        double wheelbaseMeters = 2.85;
        double trackMeters = 1.62;
        double wheelRadiusMeters = 0.34;
        double suspensionRestMeters = 0.24;
        double springNewtonsPerMeter = 46000.0;
        double damperNewtonSecondsPerMeter = 5200.0;
    };

    static std::optional<QJsonObject> readObject(const QString &path, QString *error);
    static QVector3D jsonVector(const QJsonValue &value, bool *ok);
    static QVector<double> jsonNumbers(const QJsonValue &value, bool *ok);
    static double interpolate(const QVector<double> &xs, const QVector<double> &ys, double x);
    static QQuaternion frameOrientation(const QVector3D &right, const QVector3D &up, const QVector3D &forward);
    static QQuaternion cameraLookAt(const QVector3D &position, const QVector3D &target, const QVector3D &upHint);
    static QVector3D safeNormalized(const QVector3D &value, const QVector3D &fallback);

    bool loadDescriptor(const QString &descriptorPath);
    bool loadRoad(const QString &roadPath);
    SurfaceSample sampleRoad(const QVector3D &worldPosition) const;
    QVector3D pathPoint(double station, double lateral, double height, QVector3D *forward = nullptr,
                        QVector3D *right = nullptr) const;
    QVector3D pathCenter(double station, QVector3D *forward = nullptr) const;
    void timerTick();
    void stepPhysics(double dt);
    void updateControlState(double dt);
    void updateTelemetry(const SurfaceSample &bodyRoad, double previousSpeed);
    void updateCamera();
    void setError(const QString &message);

    QTimer m_timer;
    QElapsedTimer m_clock;
    double m_accumulator = 0.0;
    bool m_ready = false;
    bool m_running = false;
    bool m_paused = false;
    bool m_autoDriveEnabled = true;
    bool m_routeEnded = false;
    QString m_errorString;
    QString m_worldId;
    QString m_worldPath;
    RoadData m_road;
    VehicleSpec m_vehicle;
    double m_gravity = 9.80665;
    double m_metersPerWorldUnit = 1.0;
    double m_snowAccumulation = 0.0;

    QVector3D m_position;
    QQuaternion m_orientation;
    QVector3D m_velocityMps;
    QVector3D m_angularVelocity;
    double m_speedMps = 0.0;
    double m_accelerationMps2 = 0.0;
    double m_steering = 0.0;
    double m_throttle = 0.0;
    double m_brake = 0.0;
    double m_routeCompletion = 0.0;
    double m_lateralErrorM = 0.0;
    int m_wheelContacts = 0;
    qulonglong m_frameId = 0;

    bool m_forwardPressed = false;
    bool m_reversePressed = false;
    bool m_leftPressed = false;
    bool m_rightPressed = false;
    bool m_brakePressed = false;

    int m_cameraMode = 1;
    double m_orbitYaw = -20.0;
    double m_orbitPitch = 14.0;
    QVector3D m_cameraPosition;
    QQuaternion m_cameraOrientation;
    QVector3D m_overlayCameraPosition;
    QQuaternion m_overlayCameraOrientation;
    QVector3D m_driverCameraPosition;
    QQuaternion m_driverCameraOrientation;
};
