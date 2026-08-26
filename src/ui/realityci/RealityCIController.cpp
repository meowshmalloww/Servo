#include "RealityCIController.h"

#include <QCoreApplication>
#include <QJsonArray>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QSettings>
#include <QUrlQuery>

namespace {
constexpr auto kTransferTimeout = 15 * 60 * 1000;
constexpr auto kDefaultBaseUrl = "http://127.0.0.1:8000";
} // namespace

RealityCIController::RealityCIController(QObject *parent)
    : QAbstractTableModel(parent)
{
    m_token = qEnvironmentVariable("SERVO_API_TOKEN");
    QSettings settings;
    m_baseUrl = settings.value("realityci/baseUrl", QString::fromLatin1(kDefaultBaseUrl))
                    .toString();
    if (m_baseUrl.isEmpty())
        m_baseUrl = QString::fromLatin1(kDefaultBaseUrl);
    if (settings.value("realityci/campaignBaseUrl").toString() == m_baseUrl) {
        m_campaignId = settings.value("realityci/campaignId").toString();
        if (!m_campaignId.isEmpty())
            m_campaignState = QStringLiteral("restoring");
    }
    m_network.setTransferTimeout(kTransferTimeout);
}

int RealityCIController::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : m_events.size();
}

int RealityCIController::columnCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : ColumnCount;
}

QVariant RealityCIController::data(const QModelIndex &index, int role) const
{
    if (!index.isValid() || index.row() < 0 || index.row() >= m_events.size())
        return {};
    const EventRow &row = m_events.at(index.row());
    switch (role) {
    case Qt::DisplayRole:
        switch (index.column()) {
        case SequenceColumn:
            return row.sequence;
        case EventColumn:
            return row.eventType;
        case DetailColumn:
        default:
            return row.detail;
        }
    case SequenceRole:
        return row.sequence;
    case EventTypeRole:
        return row.eventType;
    case CreatedAtRole:
        return row.createdAt;
    case DetailRole:
        return row.detail;
    case RecordIdRole:
        return row.recordId;
    case PayloadJsonRole: {
        const QJsonDocument document(QJsonObject::fromVariantMap(row.payload));
        return QString::fromUtf8(document.toJson(QJsonDocument::Compact));
    }
    case ArtifactCountRole:
        return row.artifactCount;
    default:
        return {};
    }
}

QHash<int, QByteArray> RealityCIController::roleNames() const
{
    return {
        { Qt::DisplayRole, "display" },
        { SequenceRole, "sequence" },
        { EventTypeRole, "eventType" },
        { CreatedAtRole, "createdAt" },
        { DetailRole, "detail" },
        { RecordIdRole, "recordId" },
        { PayloadJsonRole, "payloadJson" },
        { ArtifactCountRole, "artifactCount" }
    };
}

QVariant RealityCIController::headerData(int section, Qt::Orientation orientation, int role) const
{
    if (orientation != Qt::Horizontal || role != Qt::DisplayRole)
        return {};
    switch (section) {
    case SequenceColumn:
        return tr("SEQ");
    case EventColumn:
        return tr("EVENT");
    case DetailColumn:
    default:
        return tr("DETAIL");
    }
}

int RealityCIController::eventCount() const
{
    return m_events.size();
}

QString RealityCIController::baseUrl() const
{
    return m_baseUrl;
}

bool RealityCIController::tokenConfigured() const
{
    return !m_token.isEmpty();
}

QString RealityCIController::connectionState() const
{
    return m_connectionState;
}

bool RealityCIController::online() const
{
    return m_connectionState == QLatin1String("online");
}

bool RealityCIController::busy() const
{
    return m_busy;
}

QString RealityCIController::lastError() const
{
    return m_lastError;
}

QString RealityCIController::campaignId() const
{
    return m_campaignId;
}

QString RealityCIController::campaignState() const
{
    return m_campaignState;
}

bool RealityCIController::terminal() const
{
    return m_campaignState.startsWith(QLatin1String("completed_"))
           || m_campaignState == QLatin1String("failed")
           || m_campaignState == QLatin1String("cancelled");
}

bool RealityCIController::hasCampaign() const
{
    return !m_campaignId.isEmpty();
}

void RealityCIController::setBaseUrl(const QString &baseUrl)
{
    QString normalized = baseUrl.trimmed();
    while (normalized.endsWith(QLatin1Char('/')))
        normalized.chop(1);
    if (normalized == m_baseUrl)
        return;
    m_baseUrl = normalized;
    QSettings settings;
    settings.setValue("realityci/baseUrl", m_baseUrl);
    setConnectionState(QStringLiteral("offline"));
    emit baseUrlChanged();
}

void RealityCIController::setConnectionState(const QString &state)
{
    if (m_connectionState == state)
        return;
    m_connectionState = state;
    emit connectionStateChanged();
}

void RealityCIController::setBusy(bool value)
{
    if (m_busy == value)
        return;
    m_busy = value;
    emit busyChanged();
}

void RealityCIController::fail(const QString &message)
{
    m_lastError = message;
    setBusy(false);
    setConnectionState(QStringLiteral("error"));
    emit lastErrorChanged();
}

void RealityCIController::resetCampaign()
{
    beginResetModel();
    m_events.clear();
    endResetModel();
    m_campaignId.clear();
    m_campaignState = QStringLiteral("unknown");
    QSettings settings;
    settings.remove("realityci/campaignBaseUrl");
    settings.remove("realityci/campaignId");
    emit campaignChanged();
    emit eventsChanged();
}

void RealityCIController::clearError()
{
    if (m_lastError.isEmpty())
        return;
    m_lastError.clear();
    emit lastErrorChanged();
}

QNetworkReply *RealityCIController::get(const QString &path)
{
    QNetworkRequest request{ QUrl(m_baseUrl + path) };
    request.setAttribute(QNetworkRequest::RedirectPolicyAttribute,
                         QNetworkRequest::NoLessSafeRedirectPolicy);
    if (!m_token.isEmpty())
        request.setRawHeader("Authorization", "Bearer " + m_token.toUtf8());
    return m_network.get(request);
}

QNetworkReply *RealityCIController::post(const QString &path, const QJsonObject &body)
{
    QNetworkRequest request{ QUrl(m_baseUrl + path) };
    request.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");
    request.setAttribute(QNetworkRequest::RedirectPolicyAttribute,
                         QNetworkRequest::NoLessSafeRedirectPolicy);
    if (!m_token.isEmpty())
        request.setRawHeader("Authorization", "Bearer " + m_token.toUtf8());
    return m_network.post(request, QJsonDocument(body).toJson(QJsonDocument::Compact));
}

void RealityCIController::connectToServer()
{
    clearError();
    setBusy(true);
    setConnectionState(QStringLiteral("connecting"));
    QNetworkReply *reply = get(QStringLiteral("/healthz"));
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        reply->deleteLater();
        if (reply->error() != QNetworkReply::NoError) {
            fail(QStringLiteral("connect failed: %1").arg(reply->errorString()));
            return;
        }
        m_lastError.clear();
        emit lastErrorChanged();
        setConnectionState(QStringLiteral("online"));
        setBusy(false);
        refresh();
    });
}

void RealityCIController::applyStateJson(const QJsonObject &object)
{
    const QString id = object.value(QLatin1String("campaign_id")).toString();
    const QString state = object.value(QLatin1String("state")).toString();
    if (id.isEmpty() && state.isEmpty())
        return;
    m_campaignId = id.isEmpty() ? m_campaignId : id;
    m_campaignState = state.isEmpty() ? m_campaignState : state;
    if (!m_campaignId.isEmpty()) {
        QSettings settings;
        settings.setValue("realityci/campaignBaseUrl", m_baseUrl);
        settings.setValue("realityci/campaignId", m_campaignId);
    }
    emit campaignChanged();
}

void RealityCIController::applyEventsJson(const QJsonDocument &document)
{
    const QJsonArray events = document.object().value(QLatin1String("events")).toArray();
    QVector<EventRow> rows;
    rows.reserve(events.size());
    for (const QJsonValue &value : events) {
        const QJsonObject entry = value.toObject();
        EventRow row;
        row.sequence = static_cast<qint64>(entry.value(QLatin1String("sequence")).toDouble());
        row.recordId = entry.value(QLatin1String("record_id")).toString();
        row.eventType = entry.value(QLatin1String("event_type")).toString();
        row.createdAt = entry.value(QLatin1String("created_at")).toString();
        row.payload = entry.value(QLatin1String("payload")).toObject().toVariantMap();
        row.artifactCount = entry.value(QLatin1String("artifact_refs")).toArray().size();
        row.detail = summarize(row.eventType, row.payload);
        rows.append(row);
    }

    beginResetModel();
    m_events = rows;
    endResetModel();
    emit eventsChanged();

    if (!rows.isEmpty()) {
        m_campaignId = document.object().value(QLatin1String("campaign_id")).toString(
            m_campaignId);
        emit campaignChanged();
    }
}

void RealityCIController::refresh()
{
    if (!hasCampaign()) {
        setBusy(false);
        return;
    }
    QNetworkReply *eventsReply =
        get(QStringLiteral("/v1/campaigns/%1/events?after_sequence=0").arg(m_campaignId));
    connect(eventsReply, &QNetworkReply::finished, this, [this, eventsReply]() {
        eventsReply->deleteLater();
        if (eventsReply->error() != QNetworkReply::NoError) {
            fail(QStringLiteral("event fetch failed: %1").arg(eventsReply->errorString()));
            return;
        }
        applyEventsJson(
            QJsonDocument::fromJson(eventsReply->readAll()));
        QNetworkReply *stateReply =
            get(QStringLiteral("/v1/campaigns/%1/state").arg(m_campaignId));
        connect(stateReply, &QNetworkReply::finished, this, [this, stateReply]() {
            stateReply->deleteLater();
            if (stateReply->error() != QNetworkReply::NoError) {
                fail(QStringLiteral("state fetch failed: %1").arg(stateReply->errorString()));
                return;
            }
            applyStateJson(
                QJsonDocument::fromJson(stateReply->readAll()).object());
            setBusy(false);
        });
    });
}

void RealityCIController::createCampaign(const QString &checkpointUri,
                                         int trainingScenarios,
                                         int hiddenExamSize,
                                         int protectedSuiteSize,
                                         int trainingEpochs,
                                         double promotionTarget,
                                         double promotionFloor)
{
    if (!online()) {
        fail(QStringLiteral("not connected to a control API"));
        return;
    }
    if (checkpointUri.trimmed().isEmpty()) {
        fail(QStringLiteral("baseline checkpoint path is required"));
        return;
    }
    clearError();
    resetCampaign();
    setBusy(true);
    QJsonObject body;
    body.insert(QLatin1String("baseline_checkpoint_uri"), checkpointUri.trimmed());
    body.insert(QLatin1String("training_scenarios"), trainingScenarios);
    body.insert(QLatin1String("hidden_exam_size"), hiddenExamSize);
    body.insert(QLatin1String("protected_suite_size"), protectedSuiteSize);
    body.insert(QLatin1String("training_epochs"), trainingEpochs);
    body.insert(QLatin1String("promotion_target_success_rate"), promotionTarget);
    body.insert(QLatin1String("promotion_min_lower_bound"), promotionFloor);
    QNetworkReply *reply = post(QStringLiteral("/v1/campaigns"), body);
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        reply->deleteLater();
        if (reply->error() != QNetworkReply::NoError) {
            fail(QStringLiteral("create campaign failed: %1")
                     .arg(QString::fromUtf8(reply->readAll())));
            return;
        }
        applyStateJson(QJsonDocument::fromJson(reply->readAll()).object());
        refresh();
    });
}

void RealityCIController::stepCampaign()
{
    if (!online() || !hasCampaign()) {
        fail(QStringLiteral("create or select a campaign first"));
        return;
    }
    clearError();
    setBusy(true);
    QNetworkReply *reply =
        post(QStringLiteral("/v1/campaigns/%1/step").arg(m_campaignId), {});
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        reply->deleteLater();
        if (reply->error() != QNetworkReply::NoError) {
            fail(QStringLiteral("step failed: %1").arg(QString::fromUtf8(reply->readAll())));
            return;
        }
        applyStateJson(QJsonDocument::fromJson(reply->readAll()).object());
        refresh();
    });
}

void RealityCIController::runCampaign()
{
    if (!online() || !hasCampaign()) {
        fail(QStringLiteral("create or select a campaign first"));
        return;
    }
    clearError();
    setBusy(true);
    QNetworkReply *reply =
        post(QStringLiteral("/v1/campaigns/%1/run").arg(m_campaignId), {});
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        reply->deleteLater();
        if (reply->error() != QNetworkReply::NoError) {
            fail(QStringLiteral("run failed: %1").arg(QString::fromUtf8(reply->readAll())));
            return;
        }
        applyStateJson(QJsonDocument::fromJson(reply->readAll()).object());
        refresh();
    });
}

void RealityCIController::forgetCampaign()
{
    clearError();
    resetCampaign();
    if (online())
        setConnectionState(QStringLiteral("online"));
}

QVariantMap RealityCIController::latestPayload(const QString &eventType) const
{
    for (int index = m_events.size() - 1; index >= 0; --index) {
        if (m_events.at(index).eventType == eventType)
            return m_events.at(index).payload;
    }
    return {};
}

QVariantList RealityCIController::payloadsOf(const QString &eventType) const
{
    QVariantList result;
    for (const EventRow &row : m_events) {
        if (row.eventType == eventType) {
            QVariantMap entry = row.payload;
            entry.insert(QLatin1String("sequence"), row.sequence);
            entry.insert(QLatin1String("created_at"), row.createdAt);
            result.append(entry);
        }
    }
    return result;
}

QVariantMap RealityCIController::campaignRecord() const
{
    QVariantMap record;
    record.insert(QLatin1String("campaign_id"), m_campaignId);
    record.insert(QLatin1String("state"), m_campaignState);
    record.insert(QLatin1String("terminal"), terminal());
    record.insert(QLatin1String("events"), eventCount());
    return record;
}

QVariantMap RealityCIController::eventAt(int row) const
{
    if (row < 0 || row >= m_events.size())
        return {};
    const EventRow &event = m_events.at(row);
    QVariantMap record = event.payload;
    record.insert(QLatin1String("sequence"), event.sequence);
    record.insert(QLatin1String("record_id"), event.recordId);
    record.insert(QLatin1String("event_type"), event.eventType);
    record.insert(QLatin1String("created_at"), event.createdAt);
    record.insert(QLatin1String("detail"), event.detail);
    record.insert(QLatin1String("artifact_count"), event.artifactCount);
    record.insert(QLatin1String("payload_json"),
                  QString::fromUtf8(QJsonDocument(QJsonObject::fromVariantMap(event.payload))
                                        .toJson(QJsonDocument::Compact)));
    return record;
}

QString RealityCIController::summarize(const QString &eventType, const QVariantMap &payload)
{
    auto number = [&payload](const char *key) -> QString {
        return QString::number(payload.value(QLatin1String(key)).toReal());
    };
    if (eventType == QLatin1String("FAILURE_DETECTED"))
        return QStringLiteral("%1 · severity %2")
            .arg(payload.value(QLatin1String("failure_class")).toString(),
                 number("severity"));
    if (eventType == QLatin1String("RUN_COMPLETED"))
        return payload.value(QLatin1String("result")).toString();
    if (eventType == QLatin1String("HYPOTHESES_PROPOSED"))
        return QStringLiteral("%1 by %2")
            .arg(payload.value(QLatin1String("diagnostician")).toString(),
                 payload.value(QLatin1String("model_id")).toString());
    if (eventType == QLatin1String("EXPERIMENT_COMPLETED"))
        return QStringLiteral("%1 -> %2")
            .arg(payload.value(QLatin1String("intervention")).toString(),
                 payload.value(QLatin1String("outcome")).toString());
    if (eventType == QLatin1String("ROOT_CAUSE_ESTABLISHED"))
        return QStringLiteral("%1 (%2)")
            .arg(payload.value(QLatin1String("root_cause")).toString(),
                 payload.value(QLatin1String("rule")).toString());
    if (eventType == QLatin1String("CURRICULUM_CREATED"))
        return QStringLiteral("%1 scenarios · %2 stages")
            .arg(number("total_scenarios"),
                 QString::number(payload.value(QLatin1String("stages")).toList().size()));
    if (eventType == QLatin1String("HIDDEN_SEEDS_SEALED"))
        return QStringLiteral("%1 scenarios sealed before training")
            .arg(number("scenario_count"));
    if (eventType == QLatin1String("CHECKPOINT_READY"))
        return QStringLiteral("val loss %1")
            .arg(QString::number(
                payload.value(QLatin1String("best_val_loss")).toReal(), 'f', 4));
    if (eventType == QLatin1String("HIDDEN_EXAM_COMPLETED")) {
        const QVariantList interval =
            payload.value(QLatin1String("interval")).toList();
        return QStringLiteral("baseline %1% -> candidate %2% [95% CI %3–%4]")
            .arg(QString::number(payload
                                     .value(QLatin1String("baseline_success"))
                                     .toReal()
                                 * 100.0,
                                 'f', 1),
                 QString::number(payload
                                     .value(QLatin1String("candidate_success"))
                                     .toReal()
                                 * 100.0,
                                 'f', 1),
                 interval.size() == 2
                     ? QString::number(interval.first().toReal() * 100.0, 'f', 1)
                     : QStringLiteral("?"),
                 interval.size() == 2
                     ? QString::number(interval.last().toReal() * 100.0, 'f', 1)
                     : QStringLiteral("?"));
    }
    if (eventType == QLatin1String("REGRESSION_COMPLETED"))
        return QStringLiteral("%1 suites · max drop %2 pp")
            .arg(number("suites"), number("max_drop_pp"));
    if (eventType == QLatin1String("CHECKPOINT_PROMOTED")
        || eventType == QLatin1String("CHECKPOINT_REJECTED")) {
        const QVariantList failedChecks =
            payload.value(QLatin1String("failed_checks")).toList();
        QStringList names;
        for (const QVariant &check : failedChecks)
            names.append(check.toString());
        return names.isEmpty() ? QStringLiteral("all deterministic checks passed")
                               : names.join(QStringLiteral(", "));
    }
    if (eventType == QLatin1String("CAPABILITY_UPDATED"))
        return QStringLiteral("%1 -> %2")
            .arg(payload.value(QLatin1String("capability")).toString(),
                 payload.value(QLatin1String("state")).toString());
    if (eventType == QLatin1String("REALITY_DEBT_UPDATED"))
        return QStringLiteral("total debt %1")
            .arg(QString::number(
                payload.value(QLatin1String("total_debt")).toReal(), 'f', 3));
    if (eventType == QLatin1String("NEXT_WEAKNESS_SELECTED"))
        return payload.value(QLatin1String("taxonomy_id")).toString();
    if (eventType == QLatin1String("CAMPAIGN_COMPLETED"))
        return payload.value(QLatin1String("terminal")).toString();
    if (eventType == QLatin1String("ROOT_CAUSE_INCONCLUSIVE")
        || eventType == QLatin1String("TRAINING_FAILED")) {
        const QStringList keys = payload.keys();
        QStringList parts;
        for (const QString &key : keys)
            parts.append(key + QLatin1Char('=') + payload.value(key).toString());
        return parts.join(QStringLiteral(" "));
    }
    if (eventType == QLatin1String("BASELINE_RUN_REQUESTED"))
        return payload.value(QLatin1String("checkpoint")).toString();
    if (eventType == QLatin1String("RUN_STARTED"))
        return payload.value(QLatin1String("scenario")).toString();
    if (eventType == QLatin1String("DIAGNOSIS_REQUESTED"))
        return payload.value(QLatin1String("diagnostician")).toString();
    if (eventType == QLatin1String("TRAINING_STARTED"))
        return QStringLiteral("%1 scenarios")
            .arg(number("scenarios"));
    if (eventType == QLatin1String("CAPTURE_MISSION_CREATED"))
        return payload.value(QLatin1String("mission_id")).toString();
    if (eventType == QLatin1String("MISSING_REALITY_DETECTED"))
        return payload.value(QLatin1String("capability")).toString();
    if (eventType == QLatin1String("NO_FAILURE_FOUND"))
        return payload.value(QLatin1String("reason")).toString();
    return QString();
}
