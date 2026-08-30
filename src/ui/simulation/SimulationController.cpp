#include "SimulationController.h"
#include "SimulationFrameProvider.h"

#include <QDateTime>
#include <QDebug>
#include <QFileInfo>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QSettings>
#include <QUrl>
#include <QUuid>

namespace {
constexpr auto kDefaultBaseUrl = "http://127.0.0.1:8000";

QVector3D vectorFromJson(const QJsonObject &object)
{
    return { float(object.value(QStringLiteral("x")).toDouble()),
             float(object.value(QStringLiteral("y")).toDouble()),
             float(object.value(QStringLiteral("z")).toDouble()) };
}

QQuaternion quaternionFromJson(const QJsonObject &object)
{
    const QQuaternion value(float(object.value(QStringLiteral("w")).toDouble()),
                            float(object.value(QStringLiteral("x")).toDouble()),
                            float(object.value(QStringLiteral("y")).toDouble()),
                            float(object.value(QStringLiteral("z")).toDouble()));
    return value.isNull() ? QQuaternion() : value.normalized();
}
} // namespace

SimulationFrameProvider *SimulationController::s_frameProvider = nullptr;

SimulationController::SimulationController(QObject *parent)
    : QObject(parent)
{
    m_token = qEnvironmentVariable("SERVO_API_TOKEN");
    QSettings settings;
    m_baseUrl = settings.value("simulation/baseUrl", QString::fromLatin1(kDefaultBaseUrl)).toString();
    if (m_baseUrl.isEmpty())
        m_baseUrl = QString::fromLatin1(kDefaultBaseUrl);
    if (settings.value("simulation/sessionBaseUrl").toString() == m_baseUrl) {
        m_sessionId = settings.value("simulation/sessionId").toString();
        if (!m_sessionId.isEmpty())
            m_sessionState = QStringLiteral("reattaching");
    }
    m_network.setTransferTimeout(10000);
    m_pollTimer.setInterval(100);
    connect(&m_pollTimer, &QTimer::timeout, this, &SimulationController::poll);
    m_statusTimer.setInterval(5000);
    connect(&m_statusTimer, &QTimer::timeout, this, &SimulationController::refreshCarlaStatus);
    m_statusTimer.start();
    // A persisted session id is only a hint.  It may refer to an interrupted
    // creation whose durable manifest was never committed.  The first server
    // connection validates it against /v1/simulations before polling.
}

void SimulationController::setFrameProvider(SimulationFrameProvider *provider)
{
    s_frameProvider = provider;
}

QString SimulationController::baseUrl() const { return m_baseUrl; }
QString SimulationController::connectionState() const { return m_connectionState; }
bool SimulationController::online() const { return m_connectionState == QLatin1String("online"); }
bool SimulationController::busy() const { return m_busy; }
QString SimulationController::lastError() const { return m_lastError; }
QString SimulationController::sessionId() const { return m_sessionId; }
QString SimulationController::sessionState() const { return m_sessionState; }
bool SimulationController::hasSession() const { return !m_sessionId.isEmpty(); }
bool SimulationController::terminal() const { return m_sessionState == QLatin1String("completed") || m_sessionState == QLatin1String("failed") || m_sessionState == QLatin1String("cancelled"); }
bool SimulationController::stale() const { return m_stale; }
QString SimulationController::carlaRuntimeState() const { return m_carlaRuntimeState; }
QString SimulationController::carlaVersion() const { return m_carlaVersion; }
QString SimulationController::carlaRuntimeRoot() const { return m_carlaRuntimeRoot; }
QString SimulationController::carlaPreflightState() const { return m_carlaPreflightState; }
double SimulationController::carlaPhysicalDisplacementM() const { return m_carlaPhysicalDisplacementM; }
int SimulationController::carlaSensorFrameBytes() const { return m_carlaSensorFrameBytes; }
QString SimulationController::selectedWorldId() const { return m_selectedWorldId; }
QString SimulationController::executionWorldId() const { return m_executionWorldId; }
QString SimulationController::selectedRouteId() const { return m_selectedRouteId; }
QString SimulationController::policyName() const { return m_policyName; }
QString SimulationController::observationSource() const { return m_observationSource; }
QString SimulationController::scenarioWeather() const { return m_scenarioWeather; }
double SimulationController::scenarioSnowAccumulation() const { return m_scenarioSnowAccumulation; }
QString SimulationController::executionManifestPath() const { return m_executionManifestPath; }
bool SimulationController::executionReady() const { return m_executionReady; }
qulonglong SimulationController::frameId() const { return m_frameId; }
double SimulationController::simulationTimeS() const { return m_simulationTimeS; }
double SimulationController::speedMps() const { return m_speedMps; }
double SimulationController::accelerationMps2() const { return m_accelerationMps2; }
double SimulationController::steering() const { return m_steering; }
double SimulationController::throttle() const { return m_throttle; }
double SimulationController::brake() const { return m_brake; }
double SimulationController::targetSpeedMps() const { return m_targetSpeedMps; }
double SimulationController::routeCompletion() const { return m_routeCompletion; }
double SimulationController::lateralErrorM() const { return m_lateralErrorM; }
double SimulationController::rendererCoverage() const { return m_rendererCoverage; }
double SimulationController::policyLatencyMs() const { return m_policyLatencyMs; }
qulonglong SimulationController::policyFrameId() const { return m_policyFrameId; }
int SimulationController::collisionCount() const { return m_collisionCount; }
int SimulationController::laneInvasionCount() const { return m_laneInvasionCount; }
int SimulationController::deadlineMissCount() const { return m_deadlineMissCount; }
QVector3D SimulationController::egoPosition() const { return m_egoPosition; }
QQuaternion SimulationController::egoOrientation() const { return m_egoOrientation; }
QVector3D SimulationController::policyCameraPosition() const { return m_policyCameraPosition; }
QQuaternion SimulationController::policyCameraOrientation() const { return m_policyCameraOrientation; }
int SimulationController::policyFrameRevision() const { return m_policyFrameRevision; }
QString SimulationController::policyFrameUrl() const { return m_policyFrameUrl; }
QString SimulationController::leftPolicyFrameUrl() const { return m_leftPolicyFrameUrl; }
QString SimulationController::rightPolicyFrameUrl() const { return m_rightPolicyFrameUrl; }
QString SimulationController::nativeFrameUrl() const { return m_nativeFrameUrl; }
QString SimulationController::integratedFrameUrl() const { return m_integratedFrameUrl; }
QString SimulationController::result() const { return m_result; }
QString SimulationController::failureClass() const { return m_failureClass; }
QString SimulationController::evidencePath() const { return m_evidencePath; }
QString SimulationController::artifactPaths() const { return m_artifactPaths; }
QString SimulationController::replayVideoUrl() const { return m_replayVideoUrl; }
QString SimulationController::nativeReplayVideoUrl() const { return m_nativeReplayVideoUrl; }
QString SimulationController::hybridReplayVideoUrl() const { return m_hybridReplayVideoUrl; }
QString SimulationController::comparisonReplayVideoUrl() const { return m_comparisonReplayVideoUrl; }
bool SimulationController::physicsGatePassed() const { return m_physicsGatePassed; }
bool SimulationController::metricRealWorldValidated() const { return m_metricRealWorldValidated; }
bool SimulationController::collisionValidated() const { return m_collisionValidated; }
bool SimulationController::visualIntegrationValidated() const { return m_visualIntegrationValidated; }
QString SimulationController::visualIntegrationStatus() const { return m_visualIntegrationStatus; }

void SimulationController::setBaseUrl(const QString &value)
{
    QString normalized = value.trimmed();
    while (normalized.endsWith(QLatin1Char('/')))
        normalized.chop(1);
    if (normalized == m_baseUrl)
        return;
    m_baseUrl = normalized;
    QSettings().setValue("simulation/baseUrl", normalized);
    m_connectionState = QStringLiteral("offline");
    emit baseUrlChanged();
    emit connectionChanged();
}

void SimulationController::setBusy(bool value)
{
    if (m_busy == value)
        return;
    m_busy = value;
    emit busyChanged();
}

void SimulationController::fail(const QString &message)
{
    m_lastError = message;
    m_connectionState = QStringLiteral("error");
    setBusy(false);
    emit lastErrorChanged();
    emit connectionChanged();
}

void SimulationController::clearError()
{
    if (m_lastError.isEmpty())
        return;
    m_lastError.clear();
    emit lastErrorChanged();
}

QNetworkReply *SimulationController::get(const QString &path)
{
    QNetworkRequest request{ QUrl(m_baseUrl + path) };
    request.setAttribute(QNetworkRequest::RedirectPolicyAttribute,
                         QNetworkRequest::NoLessSafeRedirectPolicy);
    request.setRawHeader("Cache-Control", "no-store");
    if (!m_token.isEmpty())
        request.setRawHeader("Authorization", "Bearer " + m_token.toUtf8());
    return m_network.get(request);
}

QNetworkReply *SimulationController::post(const QString &path,
                                          const QJsonObject &body,
                                          const QString &idempotencyKey)
{
    QNetworkRequest request{ QUrl(m_baseUrl + path) };
    request.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");
    request.setAttribute(QNetworkRequest::RedirectPolicyAttribute,
                         QNetworkRequest::NoLessSafeRedirectPolicy);
    if (!m_token.isEmpty())
        request.setRawHeader("Authorization", "Bearer " + m_token.toUtf8());
    if (!idempotencyKey.isEmpty())
        request.setRawHeader("Idempotency-Key", idempotencyKey.toUtf8());
    return m_network.post(request, QJsonDocument(body).toJson(QJsonDocument::Compact));
}

QString SimulationController::replyError(QNetworkReply *reply, const QString &fallback) const
{
    const QByteArray bytes = reply->readAll();
    const QJsonObject root = QJsonDocument::fromJson(bytes).object();
    const QString message = root.value(QStringLiteral("error")).toObject()
                                .value(QStringLiteral("message")).toString();
    return message.isEmpty() ? fallback : message;
}

void SimulationController::connectToServer()
{
    QNetworkReply *reply = get(QStringLiteral("/healthz"));
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        reply->deleteLater();
        if (reply->error() != QNetworkReply::NoError) {
            fail(replyError(reply, reply->errorString()));
            return;
        }
        m_connectionState = QStringLiteral("online");
        emit connectionChanged();
        refreshCarlaStatus();
        fetchSimulationList(m_sessionId);
    });
}

void SimulationController::refreshCarlaStatus()
{
    QNetworkReply *reply = get(QStringLiteral("/v1/carla/status"));
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        const QByteArray bytes = reply->readAll();
        reply->deleteLater();
        if (reply->error() != QNetworkReply::NoError)
            return;
        const QJsonObject object = QJsonDocument::fromJson(bytes).object();
        m_carlaRuntimeState = object.value(QStringLiteral("status")).toString(QStringLiteral("unknown"));
        m_carlaVersion = object.value(QStringLiteral("client_version")).toString();
        m_carlaRuntimeRoot = object.value(QStringLiteral("root")).toString();
        const QJsonObject receipt = object.value(QStringLiteral("full_preflight")).toObject();
        const QJsonObject result = receipt.value(QStringLiteral("result")).toObject();
        const bool verified = result.value(QStringLiteral("ready")).toBool(false);
        m_carlaPreflightState = verified ? QStringLiteral("verified") : QStringLiteral("not-run");
        m_carlaPhysicalDisplacementM = result.value(QStringLiteral("distance_moved_m")).toDouble();
        m_carlaSensorFrameBytes = result.value(QStringLiteral("sensor_frame_bytes")).toInt();
        m_connectionState = QStringLiteral("online");
        emit runtimeChanged();
        emit connectionChanged();
    });
}

void SimulationController::verifyCarlaIntegration()
{
    if (m_busy)
        return;
    setBusy(true);
    m_carlaPreflightState = QStringLiteral("running");
    emit runtimeChanged();
    QNetworkReply *reply = post(QStringLiteral("/v1/carla/preflight"),
                                QJsonObject{{QStringLiteral("full"), true},
                                            {QStringLiteral("rendering"), true}});
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        setBusy(false);
        if (reply->error() != QNetworkReply::NoError) {
            m_carlaPreflightState = QStringLiteral("failed");
            emit runtimeChanged();
            fail(replyError(reply, reply->errorString()));
            reply->deleteLater();
            return;
        }
        const QJsonObject object = QJsonDocument::fromJson(reply->readAll()).object();
        reply->deleteLater();
        const QJsonObject result = object.value(QStringLiteral("full_preflight")).toObject()
                                       .value(QStringLiteral("result")).toObject();
        m_carlaPreflightState = result.value(QStringLiteral("ready")).toBool(false)
                                    ? QStringLiteral("verified") : QStringLiteral("failed");
        m_carlaPhysicalDisplacementM = result.value(QStringLiteral("distance_moved_m")).toDouble();
        m_carlaSensorFrameBytes = result.value(QStringLiteral("sensor_frame_bytes")).toInt();
        emit runtimeChanged();
    });
}

void SimulationController::prepareWorld(const QVariantMap &configuration)
{
    setBusy(true);
    QNetworkReply *reply = post(QStringLiteral("/v1/worlds/prepare-carla"),
                                QJsonObject::fromVariantMap(configuration));
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        setBusy(false);
        if (reply->error() != QNetworkReply::NoError) {
            fail(replyError(reply, reply->errorString()));
            reply->deleteLater();
            return;
        }
        const QByteArray bytes = reply->readAll();
        reply->deleteLater();
        const QJsonObject object = QJsonDocument::fromJson(bytes).object();
        m_executionWorldId = object.value(QStringLiteral("world_id")).toString();
        m_executionManifestPath = object.value(QStringLiteral("execution_manifest")).toString();
        m_executionReady = object.value(QStringLiteral("ready_for_carla")).toBool();
        emit configurationChanged();
        emit worldPrepared(m_executionWorldId,
                           object.value(QStringLiteral("execution_manifest")).toString());
    });
}

void SimulationController::refreshWorldExecution(const QString &worldId)
{
    const QString requestedWorldId = worldId.trimmed();
    m_executionWorldId = requestedWorldId;
    m_executionManifestPath.clear();
    m_executionReady = false;
    emit configurationChanged();
    if (requestedWorldId.isEmpty())
        return;
    QNetworkReply *reply = get(QStringLiteral("/v1/worlds/%1/execution")
                                   .arg(QString::fromUtf8(QUrl::toPercentEncoding(requestedWorldId))));
    connect(reply, &QNetworkReply::finished, this, [this, reply, requestedWorldId]() {
        if (reply->error() != QNetworkReply::NoError) {
            reply->deleteLater();
            return;
        }
        const QJsonObject root = QJsonDocument::fromJson(reply->readAll()).object();
        reply->deleteLater();
        // A user can select another world while this request is in flight.
        // Never let a late reply silently pair that selection with another
        // world's executable bundle.
        if (m_executionWorldId != requestedWorldId)
            return;
        const QJsonObject execution = root.value(QStringLiteral("execution")).toObject();
        if (execution.value(QStringLiteral("world_id")).toString() != requestedWorldId) {
            m_executionManifestPath.clear();
            m_executionReady = false;
            fail(QStringLiteral("World execution identity mismatch for %1.")
                     .arg(requestedWorldId));
            emit configurationChanged();
            return;
        }
        m_executionManifestPath = root.value(QStringLiteral("manifest_uri")).toString();
        m_executionReady = execution.value(QStringLiteral("validation")).toObject()
                               .value(QStringLiteral("ready_for_carla")).toBool();
        emit configurationChanged();
    });
}

void SimulationController::startSimulation(const QVariantMap &configuration)
{
    if (hasSession() && !terminal()) {
        fail(QStringLiteral("A non-terminal simulation session is already attached."));
        return;
    }
    const QJsonObject body = QJsonObject::fromVariantMap(configuration);
    m_selectedRouteId = body.value(QStringLiteral("route_id")).toString(QStringLiteral("primary"));
    const QJsonObject policy = body.value(QStringLiteral("policy")).toObject();
    m_policyName = policy.value(QStringLiteral("name")).toString(
        policy.value(QStringLiteral("adapter")).toString());
    m_observationSource = body.value(QStringLiteral("observation")).toObject()
                              .value(QStringLiteral("source")).toString();
    const QJsonObject scenario = body.value(QStringLiteral("scenario")).toObject();
    m_scenarioWeather = scenario.value(QStringLiteral("weather")).toString(
        QStringLiteral("clear"));
    m_scenarioSnowAccumulation = scenario.value(
        QStringLiteral("snow_accumulation")).toDouble();
    emit configurationChanged();
    setBusy(true);
    const QString idempotencyKey = QStringLiteral("servo-ui-%1").arg(
        QUuid::createUuid().toString(QUuid::WithoutBraces));
    QNetworkReply *reply = post(QStringLiteral("/v1/simulations"), body, idempotencyKey);
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        setBusy(false);
        if (reply->error() != QNetworkReply::NoError) {
            fail(replyError(reply, reply->errorString()));
            reply->deleteLater();
            return;
        }
        const QByteArray bytes = reply->readAll();
        reply->deleteLater();
        const QJsonObject object = QJsonDocument::fromJson(bytes).object();
        const QString acceptedWorldId = object.value(QStringLiteral("world_id")).toString();
        if (acceptedWorldId.isEmpty() || acceptedWorldId != m_executionWorldId) {
            fail(QStringLiteral("Simulation service accepted a different world than the selected execution bundle."));
            return;
        }
        m_sessionId = object.value(QStringLiteral("session_id")).toString();
        m_sessionState = object.value(QStringLiteral("state")).toString(QStringLiteral("created"));
        // Bind the attached session only after the API has accepted the
        // executable-world request.  Merely inspecting another world must not
        // make an unrelated or stale session appear to match it.
        m_selectedWorldId = m_executionWorldId;
        m_policyFrameId = 0;
        m_policyFrameRevision = 0;
        m_frameRequestActive = false;
        m_policyFrameUrl.clear();
        m_leftPolicyFrameUrl.clear();
        m_rightPolicyFrameUrl.clear();
        m_nativeFrameUrl.clear();
        m_integratedFrameUrl.clear();
        m_evidencePath.clear();
        m_artifactPaths.clear();
        m_replayVideoUrl.clear();
        m_nativeReplayVideoUrl.clear();
        m_hybridReplayVideoUrl.clear();
        m_comparisonReplayVideoUrl.clear();
        m_physicsGatePassed = false;
        m_metricRealWorldValidated = false;
        m_collisionValidated = false;
        m_visualIntegrationValidated = false;
        m_visualIntegrationStatus = QStringLiteral("not-evaluated");
        QSettings settings;
        settings.setValue("simulation/sessionBaseUrl", m_baseUrl);
        settings.setValue("simulation/sessionId", m_sessionId);
        m_pollTimer.start();
        emit sessionChanged();
        emit policyFrameChanged();
    });
}

void SimulationController::command(const QString &name)
{
    if (!hasSession())
        return;
    QNetworkReply *reply = post(QStringLiteral("/v1/simulations/%1/%2").arg(m_sessionId, name), {});
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        reply->deleteLater();
        if (reply->error() != QNetworkReply::NoError)
            fail(replyError(reply, reply->errorString()));
    });
}

void SimulationController::pauseSimulation() { command(QStringLiteral("pause")); }
void SimulationController::resumeSimulation() { command(QStringLiteral("resume")); }
void SimulationController::stopSimulation() { command(QStringLiteral("stop")); }
void SimulationController::resetSimulation() { stopSimulation(); }

void SimulationController::reattachSimulation(const QString &sessionId)
{
    const QString normalized = sessionId.trimmed();
    if (normalized.isEmpty())
        return;
    fetchSimulationList(normalized);
}

void SimulationController::reattachLatestSimulation()
{
    fetchSimulationList({});
}

void SimulationController::fetchSimulationList(const QString &preferredSessionId)
{
    if (m_busy)
        return;
    setBusy(true);
    QNetworkReply *reply = get(QStringLiteral("/v1/simulations"));
    connect(reply, &QNetworkReply::finished, this, [this, reply, preferredSessionId]() {
        if (reply->error() != QNetworkReply::NoError) {
            const QString message = replyError(reply, reply->errorString());
            reply->deleteLater();
            fail(message);
            return;
        }
        const QJsonArray sessions = QJsonDocument::fromJson(reply->readAll()).object()
                                        .value(QStringLiteral("simulations")).toArray();
        reply->deleteLater();
        setBusy(false);
        const QString requiredWorldId = m_executionWorldId;
        const QJsonObject selectedEntry = selectSimulationEntry(
            sessions, preferredSessionId, requiredWorldId);
        if (selectedEntry.isEmpty()) {
            if (!preferredSessionId.isEmpty())
                qWarning() << "Discarding missing or wrong-world persisted simulation"
                           << preferredSessionId << "for world" << requiredWorldId;
            clearAttachedSimulation();
            m_connectionState = QStringLiteral("online");
            emit connectionChanged();
            return;
        }
        attachSimulationEntry(selectedEntry);
    });
}

QJsonObject SimulationController::selectSimulationEntry(
    const QJsonArray &sessions,
    const QString &preferredSessionId,
    const QString &requiredWorldId)
{
    QString effectiveWorldId = requiredWorldId;
    // Startup can fetch sessions before Worlds publishes its selection. Keep
    // the persisted session's world as a migration hint even when that exact
    // legacy session fails the newer evidence gate.
    if (effectiveWorldId.isEmpty() && !preferredSessionId.isEmpty()) {
        for (const QJsonValue &value : sessions) {
            const QJsonObject entry = value.toObject();
            if (entry.value(QStringLiteral("session_id")).toString()
                == preferredSessionId) {
                effectiveWorldId = entry.value(QStringLiteral("world_id")).toString();
                break;
            }
        }
    }
    const auto eligible = [&effectiveWorldId](const QJsonObject &entry) {
        return effectiveWorldId.isEmpty()
               || entry.value(QStringLiteral("world_id")).toString() == effectiveWorldId;
    };
    const auto verifiedDefault = [&eligible](const QJsonObject &entry) {
        if (!eligible(entry))
            return false;
        const bool completedSuccess =
            entry.value(QStringLiteral("state")).toString() == QLatin1String("completed")
            && entry.value(QStringLiteral("outcome")).toString() == QLatin1String("success");
        return !completedSuccess
               || entry.value(QStringLiteral("session_evidence_verified")).toBool();
    };
    if (!preferredSessionId.isEmpty()) {
        for (const QJsonValue &value : sessions) {
            const QJsonObject entry = value.toObject();
            if (verifiedDefault(entry)
                && entry.value(QStringLiteral("session_id")).toString()
                       == preferredSessionId) {
                return entry;
            }
        }
    }
    for (const QJsonValue &value : sessions) {
        const QJsonObject entry = value.toObject();
        if (eligible(entry)
            && entry.value(QStringLiteral("state")).toString() == QLatin1String("completed")
            && entry.value(QStringLiteral("outcome")).toString() == QLatin1String("success")
            && entry.value(QStringLiteral("session_evidence_verified")).toBool()) {
            return entry;
        }
    }
    for (const QJsonValue &value : sessions) {
        const QJsonObject entry = value.toObject();
        if (eligible(entry)
            && entry.value(QStringLiteral("state")).toString() == QLatin1String("completed")) {
            return entry;
        }
    }
    for (const QJsonValue &value : sessions) {
        const QJsonObject entry = value.toObject();
        if (eligible(entry))
            return entry;
    }
    return {};
}

void SimulationController::attachSimulationEntry(const QJsonObject &entry)
{
    m_sessionId = entry.value(QStringLiteral("session_id")).toString();
    if (m_sessionId.isEmpty()) {
        fail(QStringLiteral("Simulation list entry is missing session_id."));
        return;
    }
    m_sessionState = QStringLiteral("reattaching");
    m_selectedWorldId = entry.value(QStringLiteral("world_id")).toString();
    m_selectedRouteId = entry.value(QStringLiteral("route_id")).toString();
    m_policyName = entry.value(QStringLiteral("policy_name")).toString();
    m_observationSource = entry.value(QStringLiteral("observation_source")).toString();
    m_scenarioWeather = entry.value(QStringLiteral("weather")).toString();
    m_scenarioSnowAccumulation = entry.value(
        QStringLiteral("snow_accumulation")).toDouble();
    m_sequence = 0;
    m_policyFrameId = 0;
    m_policyFrameRevision = 0;
    m_frameRequestActive = false;
    m_policyFrameUrl.clear();
    m_leftPolicyFrameUrl.clear();
    m_rightPolicyFrameUrl.clear();
    m_nativeFrameUrl.clear();
    m_integratedFrameUrl.clear();
    m_evidencePath.clear();
    m_artifactPaths.clear();
    m_replayVideoUrl.clear();
    m_nativeReplayVideoUrl.clear();
    m_hybridReplayVideoUrl.clear();
    m_comparisonReplayVideoUrl.clear();
    m_physicsGatePassed = false;
    m_metricRealWorldValidated = false;
    m_collisionValidated = false;
    m_visualIntegrationValidated = false;
    m_visualIntegrationStatus = QStringLiteral("not-evaluated");
    QSettings settings;
    settings.setValue("simulation/sessionBaseUrl", m_baseUrl);
    settings.setValue("simulation/sessionId", m_sessionId);
    m_pollTimer.start();
    emit configurationChanged();
    emit sessionChanged();
    emit policyFrameChanged();
}

void SimulationController::forgetSimulation()
{
    if (hasSession() && !terminal()) {
        fail(QStringLiteral("Stop the active simulation before forgetting it."));
        return;
    }
    clearAttachedSimulation();
}

void SimulationController::clearAttachedSimulation()
{
    m_pollTimer.stop();
    m_sessionId.clear();
    m_sessionState = QStringLiteral("none");
    m_selectedWorldId.clear();
    m_selectedRouteId.clear();
    m_policyName.clear();
    m_observationSource.clear();
    m_scenarioWeather.clear();
    m_scenarioSnowAccumulation = 0.0;
    m_sequence = 0;
    m_frameId = 0;
    m_policyFrameId = 0;
    m_policyFrameRevision = 0;
    m_frameRequestActive = false;
    m_policyFrameUrl.clear();
    m_leftPolicyFrameUrl.clear();
    m_rightPolicyFrameUrl.clear();
    m_nativeFrameUrl.clear();
    m_integratedFrameUrl.clear();
    m_evidencePath.clear();
    m_artifactPaths.clear();
    m_replayVideoUrl.clear();
    m_nativeReplayVideoUrl.clear();
    m_hybridReplayVideoUrl.clear();
    m_comparisonReplayVideoUrl.clear();
    m_physicsGatePassed = false;
    m_metricRealWorldValidated = false;
    m_collisionValidated = false;
    m_visualIntegrationValidated = false;
    m_visualIntegrationStatus = QStringLiteral("not-evaluated");
    QSettings settings;
    settings.remove("simulation/sessionBaseUrl");
    settings.remove("simulation/sessionId");
    emit configurationChanged();
    emit sessionChanged();
    emit policyFrameChanged();
}

void SimulationController::poll()
{
    if (!hasSession() || m_liveRequestActive)
        return;
    m_liveRequestActive = true;
    const QString requestedSession = m_sessionId;
    QNetworkReply *stateReply = get(QStringLiteral("/v1/simulations/%1/state").arg(requestedSession));
    connect(stateReply, &QNetworkReply::finished, this, [this, stateReply, requestedSession]() {
        const QByteArray bytes = stateReply->readAll();
        const int status = stateReply->attribute(
            QNetworkRequest::HttpStatusCodeAttribute).toInt();
        const bool missing = stateReply->error() != QNetworkReply::NoError
                             && status == 404;
        stateReply->deleteLater();
        if (!missing && stateReply->error() == QNetworkReply::NoError)
            applyState(QJsonDocument::fromJson(bytes).object());
        else if (missing && m_sessionId == requestedSession) {
            qWarning() << "Attached simulation disappeared from durable storage"
                       << requestedSession;
            clearAttachedSimulation();
            QTimer::singleShot(0, this,
                               [this]() { fetchSimulationList({}); });
        }
    });
    QNetworkReply *liveReply = get(QStringLiteral("/v1/simulations/%1/live").arg(requestedSession));
    connect(liveReply, &QNetworkReply::finished, this, [this, liveReply, requestedSession]() {
        const QByteArray bytes = liveReply->readAll();
        liveReply->deleteLater();
        m_liveRequestActive = false;
        if (liveReply->error() == QNetworkReply::NoError
            && m_sessionId == requestedSession) {
            applyLive(QJsonDocument::fromJson(bytes).object());
            m_connectionState = QStringLiteral("online");
            emit connectionChanged();
        }
    });
}

void SimulationController::applyState(const QJsonObject &object)
{
    const QString next = object.value(QStringLiteral("state")).toString();
    if (!next.isEmpty() && next != m_sessionState) {
        m_sessionState = next;
        if (next == QLatin1String("failed"))
            m_failureClass = object.value(QStringLiteral("detail")).toString();
        emit sessionChanged();
        emit liveChanged();
    }
    if (terminal() && m_evidencePath.isEmpty())
        fetchEvidence();
}

void SimulationController::applyLive(const QJsonObject &object)
{
    const qulonglong sequence = object.value(QStringLiteral("sequence")).toInteger();
    if (sequence < m_sequence)
        return;
    m_sequence = sequence;
    m_frameId = object.value(QStringLiteral("authoritative_frame")).toInteger();
    m_simulationTimeS = object.value(QStringLiteral("simulation_time_s")).toDouble();
    m_speedMps = object.value(QStringLiteral("speed_mps")).toDouble();
    m_accelerationMps2 = object.value(QStringLiteral("acceleration_mps2")).toDouble();
    m_steering = object.value(QStringLiteral("steering")).toDouble();
    m_throttle = object.value(QStringLiteral("throttle")).toDouble();
    m_brake = object.value(QStringLiteral("brake")).toDouble();
    m_targetSpeedMps = object.value(QStringLiteral("target_speed_mps")).toDouble();
    m_routeCompletion = object.value(QStringLiteral("route_completion")).toDouble();
    m_lateralErrorM = object.value(QStringLiteral("lateral_error_m")).toDouble();
    m_rendererCoverage = object.value(QStringLiteral("renderer_coverage")).toDouble();
    m_policyLatencyMs = object.value(QStringLiteral("policy_latency_ms")).toDouble();
    m_collisionCount = object.value(QStringLiteral("collision_count")).toInt();
    m_laneInvasionCount = object.value(QStringLiteral("lane_invasion_count")).toInt();
    m_deadlineMissCount = object.value(QStringLiteral("deadline_miss_count")).toInt();
    const QJsonObject servoPose = object.value(QStringLiteral("ego_pose_servo")).toObject();
    m_egoPosition = vectorFromJson(servoPose.value(QStringLiteral("position")).toObject());
    m_egoOrientation = quaternionFromJson(servoPose.value(QStringLiteral("orientation")).toObject());
    const QJsonObject policyCameraPose = object.value(QStringLiteral("policy_camera_pose_servo")).toObject();
    m_policyCameraPosition = vectorFromJson(policyCameraPose.value(QStringLiteral("position")).toObject());
    m_policyCameraOrientation = quaternionFromJson(policyCameraPose.value(QStringLiteral("orientation")).toObject());
    m_result = object.value(QStringLiteral("current_result")).toString();
    m_failureClass = object.value(QStringLiteral("last_failure")).toString();
    const QDateTime updated = QDateTime::fromString(
        object.value(QStringLiteral("wall_clock_updated_at")).toString(), Qt::ISODateWithMs);
    const bool nextStale = !updated.isValid() || updated.msecsTo(QDateTime::currentDateTimeUtc()) > 3000;
    m_stale = nextStale;
    const qulonglong nextPolicyFrame = object.value(QStringLiteral("policy_frame_id")).toInteger();
    const bool frameChanged = nextPolicyFrame > m_policyFrameId;
    m_policyFrameId = nextPolicyFrame;
    if (m_sequence == sequence && m_nativeFrameUrl.isEmpty())
        qInfo() << "Simulation live frame" << m_sessionId << "sequence" << sequence
                << "policy frame" << m_policyFrameId;
    emit liveChanged();
    if (frameChanged || (m_policyFrameId > 0 && m_nativeFrameUrl.isEmpty()))
        fetchPolicyFrame();
}

void SimulationController::fetchPolicyFrame()
{
    if (!hasSession() || m_policyFrameId == 0 || m_frameRequestActive)
        return;
    m_frameRequestActive = true;
    const qulonglong requestedFrame = m_policyFrameId;
    QNetworkReply *reply = get(QStringLiteral("/v1/simulations/%1/policy-frame?frame=%2")
                                   .arg(m_sessionId)
                                   .arg(requestedFrame));
    connect(reply, &QNetworkReply::finished, this, [this, reply, requestedFrame]() {
        const QByteArray bytes = reply->readAll();
        reply->deleteLater();
        if (reply->error() != QNetworkReply::NoError || requestedFrame != m_policyFrameId)
            return;
        const QImage image = QImage::fromData(bytes);
        if (image.isNull() || !s_frameProvider)
            return;
        s_frameProvider->publish(image, m_sessionId, requestedFrame);
        ++m_policyFrameRevision;
        m_policyFrameUrl = QStringLiteral("image://simulation-policy/%1/%2?revision=%3")
                               .arg(m_sessionId)
                               .arg(requestedFrame)
                               .arg(m_policyFrameRevision);
        emit policyFrameChanged();
    });
    const auto requestSideCamera = [this, requestedFrame](const QString &cameraId) {
        QNetworkReply *cameraReply = get(
            QStringLiteral("/v1/simulations/%1/policy-frame/%2?frame=%3")
                .arg(m_sessionId, cameraId).arg(requestedFrame));
        connect(cameraReply, &QNetworkReply::finished, this,
                [this, cameraReply, requestedFrame, cameraId]() {
            const QByteArray bytes = cameraReply->readAll();
            cameraReply->deleteLater();
            if (cameraReply->error() != QNetworkReply::NoError
                || requestedFrame != m_policyFrameId || !s_frameProvider)
                return;
            const QImage image = QImage::fromData(bytes);
            if (image.isNull())
                return;
            const QString key = m_sessionId + QLatin1Char('-') + cameraId;
            s_frameProvider->publish(image, key, requestedFrame);
            ++m_policyFrameRevision;
            const QString url = QStringLiteral("image://simulation-policy/%1/%2?revision=%3")
                                    .arg(key).arg(requestedFrame).arg(m_policyFrameRevision);
            if (cameraId == QLatin1String("front_left"))
                m_leftPolicyFrameUrl = url;
            else
                m_rightPolicyFrameUrl = url;
            emit policyFrameChanged();
        });
    };
    requestSideCamera(QStringLiteral("front_left"));
    requestSideCamera(QStringLiteral("front_right"));
    QNetworkReply *nativeReply = get(
        QStringLiteral("/v1/simulations/%1/native-frame?frame=%2")
            .arg(m_sessionId).arg(requestedFrame));
    connect(nativeReply, &QNetworkReply::finished,
            this, [this, nativeReply, requestedFrame]() {
        const QByteArray bytes = nativeReply->readAll();
        nativeReply->deleteLater();
        m_frameRequestActive = false;
        if (nativeReply->error() != QNetworkReply::NoError
            || requestedFrame != m_policyFrameId || !s_frameProvider)
            return;
        const QImage image = QImage::fromData(bytes);
        if (image.isNull())
            return;
        const QString key = m_sessionId + QStringLiteral("-native");
        s_frameProvider->publish(image, key, requestedFrame);
        ++m_policyFrameRevision;
        m_nativeFrameUrl = QStringLiteral("image://simulation-policy/%1/%2?revision=%3")
                               .arg(key).arg(requestedFrame).arg(m_policyFrameRevision);
        emit policyFrameChanged();
    });
}

void SimulationController::fetchEvidence()
{
    if (!hasSession() || m_evidenceRequestActive)
        return;
    m_evidenceRequestActive = true;
    QNetworkReply *reply = get(QStringLiteral("/v1/simulations/%1/evidence").arg(m_sessionId));
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        const QByteArray bytes = reply->readAll();
        m_evidenceRequestActive = false;
        if (reply->error() != QNetworkReply::NoError) {
            reply->deleteLater();
            return;
        }
        const QJsonObject root = QJsonDocument::fromJson(bytes).object();
        reply->deleteLater();
        applyEvidence(root);
    });
}

void SimulationController::applyEvidence(const QJsonObject &root)
{
    const QJsonObject evidence = root.value(QStringLiteral("evidence")).toObject();
    const QJsonObject artifacts = root.value(QStringLiteral("artifact_paths")).toObject();
    const QJsonObject physics = root.value(QStringLiteral("physics_evidence")).toObject();
    const QJsonObject visual = root.value(QStringLiteral("visual_integration")).toObject();
    m_result = evidence.value(QStringLiteral("outcome")).toString(m_result);
    m_failureClass = evidence.value(QStringLiteral("failure_class")).toString(m_failureClass);
    m_evidencePath = root.value(QStringLiteral("run_evidence_uri")).toString();
    m_artifactPaths = QString::fromUtf8(
        QJsonDocument(artifacts).toJson(QJsonDocument::Compact));

    const auto artifactUrl = [&artifacts](const QString &key) {
        const QString path = artifacts.value(key).toString();
        return !path.isEmpty() && QFileInfo::exists(path)
                   ? QUrl::fromLocalFile(QFileInfo(path).absoluteFilePath()).toString()
                   : QString();
    };
    m_nativeReplayVideoUrl = artifactUrl(
        QStringLiteral("evidence/carla-native-fixed.mp4"));
    // Legacy composite artifacts remain in artifactPaths so an investigator
    // can reproduce the rejection. They are deliberately not exposed as
    // playable product views.
    m_hybridReplayVideoUrl.clear();
    m_comparisonReplayVideoUrl.clear();
    m_integratedFrameUrl.clear();
    m_replayVideoUrl = m_nativeReplayVideoUrl;
    m_physicsGatePassed = physics.value(QStringLiteral("physics_gate_pass")).toBool(false);
    m_metricRealWorldValidated = physics.value(
        QStringLiteral("metric_real_world_validated")).toBool(false);
    m_collisionValidated = physics.value(
        QStringLiteral("collision_validated")).toBool(false);
    m_visualIntegrationValidated = visual.value(
        QStringLiteral("submission_eligible")).toBool(false);
    m_visualIntegrationStatus = visual.value(
        QStringLiteral("status")).toString(QStringLiteral("rejected"));
    emit liveChanged();
    emit evidenceChanged();
}
