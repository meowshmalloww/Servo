#pragma once

#include <QNetworkAccessManager>
#include <QObject>
#include <QQuaternion>
#include <QString>
#include <QTimer>
#include <QVariantMap>
#include <QVector3D>
#include <QtQmlIntegration>

class QJsonObject;
class QNetworkReply;
class SimulationFrameProvider;

class SimulationController final : public QObject
{
    Q_OBJECT
    QML_NAMED_ELEMENT(SimulationController)
    QML_SINGLETON

    Q_PROPERTY(QString baseUrl READ baseUrl WRITE setBaseUrl NOTIFY baseUrlChanged)
    Q_PROPERTY(QString connectionState READ connectionState NOTIFY connectionChanged)
    Q_PROPERTY(bool online READ online NOTIFY connectionChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString lastError READ lastError NOTIFY lastErrorChanged)
    Q_PROPERTY(QString sessionId READ sessionId NOTIFY sessionChanged)
    Q_PROPERTY(QString sessionState READ sessionState NOTIFY sessionChanged)
    Q_PROPERTY(bool hasSession READ hasSession NOTIFY sessionChanged)
    Q_PROPERTY(bool terminal READ terminal NOTIFY sessionChanged)
    Q_PROPERTY(bool stale READ stale NOTIFY liveChanged)
    Q_PROPERTY(QString carlaRuntimeState READ carlaRuntimeState NOTIFY runtimeChanged)
    Q_PROPERTY(QString carlaVersion READ carlaVersion NOTIFY runtimeChanged)
    Q_PROPERTY(QString carlaRuntimeRoot READ carlaRuntimeRoot NOTIFY runtimeChanged)
    Q_PROPERTY(QString carlaPreflightState READ carlaPreflightState NOTIFY runtimeChanged)
    Q_PROPERTY(double carlaPhysicalDisplacementM READ carlaPhysicalDisplacementM NOTIFY runtimeChanged)
    Q_PROPERTY(int carlaSensorFrameBytes READ carlaSensorFrameBytes NOTIFY runtimeChanged)
    Q_PROPERTY(QString selectedWorldId READ selectedWorldId NOTIFY configurationChanged)
    Q_PROPERTY(QString executionWorldId READ executionWorldId NOTIFY configurationChanged)
    Q_PROPERTY(QString selectedRouteId READ selectedRouteId NOTIFY configurationChanged)
    Q_PROPERTY(QString policyName READ policyName NOTIFY configurationChanged)
    Q_PROPERTY(QString observationSource READ observationSource NOTIFY configurationChanged)
    Q_PROPERTY(QString scenarioWeather READ scenarioWeather NOTIFY configurationChanged)
    Q_PROPERTY(double scenarioSnowAccumulation READ scenarioSnowAccumulation NOTIFY configurationChanged)
    Q_PROPERTY(QString executionManifestPath READ executionManifestPath NOTIFY configurationChanged)
    Q_PROPERTY(bool executionReady READ executionReady NOTIFY configurationChanged)
    Q_PROPERTY(qulonglong frameId READ frameId NOTIFY liveChanged)
    Q_PROPERTY(double simulationTimeS READ simulationTimeS NOTIFY liveChanged)
    Q_PROPERTY(double speedMps READ speedMps NOTIFY liveChanged)
    Q_PROPERTY(double accelerationMps2 READ accelerationMps2 NOTIFY liveChanged)
    Q_PROPERTY(double steering READ steering NOTIFY liveChanged)
    Q_PROPERTY(double throttle READ throttle NOTIFY liveChanged)
    Q_PROPERTY(double brake READ brake NOTIFY liveChanged)
    Q_PROPERTY(double targetSpeedMps READ targetSpeedMps NOTIFY liveChanged)
    Q_PROPERTY(double routeCompletion READ routeCompletion NOTIFY liveChanged)
    Q_PROPERTY(double lateralErrorM READ lateralErrorM NOTIFY liveChanged)
    Q_PROPERTY(double rendererCoverage READ rendererCoverage NOTIFY liveChanged)
    Q_PROPERTY(double policyLatencyMs READ policyLatencyMs NOTIFY liveChanged)
    Q_PROPERTY(qulonglong policyFrameId READ policyFrameId NOTIFY liveChanged)
    Q_PROPERTY(int collisionCount READ collisionCount NOTIFY liveChanged)
    Q_PROPERTY(int laneInvasionCount READ laneInvasionCount NOTIFY liveChanged)
    Q_PROPERTY(int deadlineMissCount READ deadlineMissCount NOTIFY liveChanged)
    Q_PROPERTY(QVector3D egoPosition READ egoPosition NOTIFY liveChanged)
    Q_PROPERTY(QQuaternion egoOrientation READ egoOrientation NOTIFY liveChanged)
    Q_PROPERTY(QVector3D policyCameraPosition READ policyCameraPosition NOTIFY liveChanged)
    Q_PROPERTY(QQuaternion policyCameraOrientation READ policyCameraOrientation NOTIFY liveChanged)
    Q_PROPERTY(int policyFrameRevision READ policyFrameRevision NOTIFY policyFrameChanged)
    Q_PROPERTY(QString policyFrameUrl READ policyFrameUrl NOTIFY policyFrameChanged)
    Q_PROPERTY(QString leftPolicyFrameUrl READ leftPolicyFrameUrl NOTIFY policyFrameChanged)
    Q_PROPERTY(QString rightPolicyFrameUrl READ rightPolicyFrameUrl NOTIFY policyFrameChanged)
    Q_PROPERTY(QString integratedFrameUrl READ integratedFrameUrl NOTIFY policyFrameChanged)
    Q_PROPERTY(QString result READ result NOTIFY liveChanged)
    Q_PROPERTY(QString failureClass READ failureClass NOTIFY liveChanged)
    Q_PROPERTY(QString evidencePath READ evidencePath NOTIFY evidenceChanged)
    Q_PROPERTY(QString artifactPaths READ artifactPaths NOTIFY evidenceChanged)
    Q_PROPERTY(QString replayVideoUrl READ replayVideoUrl NOTIFY evidenceChanged)

public:
    explicit SimulationController(QObject *parent = nullptr);
    static void setFrameProvider(SimulationFrameProvider *provider);

    QString baseUrl() const;
    QString connectionState() const;
    bool online() const;
    bool busy() const;
    QString lastError() const;
    QString sessionId() const;
    QString sessionState() const;
    bool hasSession() const;
    bool terminal() const;
    bool stale() const;
    QString carlaRuntimeState() const;
    QString carlaVersion() const;
    QString carlaRuntimeRoot() const;
    QString carlaPreflightState() const;
    double carlaPhysicalDisplacementM() const;
    int carlaSensorFrameBytes() const;
    QString selectedWorldId() const;
    QString executionWorldId() const;
    QString selectedRouteId() const;
    QString policyName() const;
    QString observationSource() const;
    QString scenarioWeather() const;
    double scenarioSnowAccumulation() const;
    QString executionManifestPath() const;
    bool executionReady() const;
    qulonglong frameId() const;
    double simulationTimeS() const;
    double speedMps() const;
    double accelerationMps2() const;
    double steering() const;
    double throttle() const;
    double brake() const;
    double targetSpeedMps() const;
    double routeCompletion() const;
    double lateralErrorM() const;
    double rendererCoverage() const;
    double policyLatencyMs() const;
    qulonglong policyFrameId() const;
    int collisionCount() const;
    int laneInvasionCount() const;
    int deadlineMissCount() const;
    QVector3D egoPosition() const;
    QQuaternion egoOrientation() const;
    QVector3D policyCameraPosition() const;
    QQuaternion policyCameraOrientation() const;
    int policyFrameRevision() const;
    QString policyFrameUrl() const;
    QString leftPolicyFrameUrl() const;
    QString rightPolicyFrameUrl() const;
    QString integratedFrameUrl() const;
    QString result() const;
    QString failureClass() const;
    QString evidencePath() const;
    QString artifactPaths() const;
    QString replayVideoUrl() const;

    Q_INVOKABLE void setBaseUrl(const QString &value);
    Q_INVOKABLE void connectToServer();
    Q_INVOKABLE void refreshCarlaStatus();
    Q_INVOKABLE void verifyCarlaIntegration();
    Q_INVOKABLE void prepareWorld(const QVariantMap &configuration);
    Q_INVOKABLE void refreshWorldExecution(const QString &worldId);
    Q_INVOKABLE void startSimulation(const QVariantMap &configuration);
    Q_INVOKABLE void pauseSimulation();
    Q_INVOKABLE void resumeSimulation();
    Q_INVOKABLE void stopSimulation();
    Q_INVOKABLE void resetSimulation();
    Q_INVOKABLE void reattachSimulation(const QString &sessionId);
    Q_INVOKABLE void reattachLatestSimulation();
    Q_INVOKABLE void forgetSimulation();
    Q_INVOKABLE void clearError();

signals:
    void baseUrlChanged();
    void connectionChanged();
    void busyChanged();
    void lastErrorChanged();
    void sessionChanged();
    void runtimeChanged();
    void configurationChanged();
    void liveChanged();
    void policyFrameChanged();
    void evidenceChanged();
    void worldPrepared(const QString &worldId, const QString &manifestPath);

private:
    friend class SimulationControllerTests;
    QNetworkReply *get(const QString &path);
    QNetworkReply *post(const QString &path, const QJsonObject &body, const QString &idempotencyKey = {});
    QString replyError(QNetworkReply *reply, const QString &fallback) const;
    void poll();
    void fetchPolicyFrame();
    void fetchEvidence();
    void applyEvidence(const QJsonObject &object);
    void applyLive(const QJsonObject &object);
    void applyState(const QJsonObject &object);
    void fetchSimulationList(const QString &preferredSessionId);
    void attachSimulationEntry(const QJsonObject &entry);
    void clearAttachedSimulation();
    void setBusy(bool value);
    void fail(const QString &message);
    void command(const QString &name);

    static SimulationFrameProvider *s_frameProvider;
    QNetworkAccessManager m_network;
    QTimer m_pollTimer;
    QTimer m_statusTimer;
    QString m_baseUrl;
    QString m_token;
    QString m_connectionState = QStringLiteral("offline");
    QString m_lastError;
    QString m_sessionId;
    QString m_sessionState = QStringLiteral("none");
    QString m_carlaRuntimeState = QStringLiteral("not-configured");
    QString m_carlaVersion;
    QString m_carlaRuntimeRoot;
    QString m_carlaPreflightState = QStringLiteral("not-run");
    double m_carlaPhysicalDisplacementM = 0.0;
    int m_carlaSensorFrameBytes = 0;
    QString m_selectedWorldId;
    QString m_executionWorldId;
    QString m_selectedRouteId;
    QString m_policyName;
    QString m_observationSource;
    QString m_scenarioWeather;
    double m_scenarioSnowAccumulation = 0.0;
    QString m_executionManifestPath;
    QString m_policyFrameUrl;
    QString m_leftPolicyFrameUrl;
    QString m_rightPolicyFrameUrl;
    QString m_integratedFrameUrl;
    QString m_result;
    QString m_failureClass;
    QString m_evidencePath;
    QString m_artifactPaths;
    QString m_replayVideoUrl;
    QVector3D m_egoPosition;
    QQuaternion m_egoOrientation;
    QVector3D m_policyCameraPosition;
    QQuaternion m_policyCameraOrientation;
    qulonglong m_sequence = 0;
    qulonglong m_frameId = 0;
    qulonglong m_policyFrameId = 0;
    double m_simulationTimeS = 0.0;
    double m_speedMps = 0.0;
    double m_accelerationMps2 = 0.0;
    double m_steering = 0.0;
    double m_throttle = 0.0;
    double m_brake = 0.0;
    double m_targetSpeedMps = 0.0;
    double m_routeCompletion = 0.0;
    double m_lateralErrorM = 0.0;
    double m_rendererCoverage = 0.0;
    double m_policyLatencyMs = 0.0;
    int m_collisionCount = 0;
    int m_laneInvasionCount = 0;
    int m_deadlineMissCount = 0;
    int m_policyFrameRevision = 0;
    bool m_busy = false;
    bool m_stale = false;
    bool m_liveRequestActive = false;
    bool m_frameRequestActive = false;
    bool m_executionReady = false;
    bool m_evidenceRequestActive = false;
};
