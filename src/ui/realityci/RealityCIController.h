#pragma once

#include <QAbstractTableModel>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QStringList>
#include <QUrl>
#include <QVariantList>
#include <QVariantMap>
#include <QtQmlIntegration>

class QNetworkReply;

// Durable RealityCI campaign client.
//
// Every displayed value originates from a backend record served by the
// control API (local uvicorn today, Cloud Run later). The controller never
// synthesizes progress: unknown states stay "unknown", and errors surface
// verbatim through lastError.
class RealityCIController final : public QAbstractTableModel
{
    Q_OBJECT
    QML_NAMED_ELEMENT(RealityCIController)
    QML_SINGLETON

    // Column identity for TableView-based tables.
    Q_PROPERTY(int eventCount READ eventCount NOTIFY eventsChanged)
    Q_PROPERTY(QString baseUrl READ baseUrl WRITE setBaseUrl NOTIFY baseUrlChanged)
    Q_PROPERTY(bool tokenConfigured READ tokenConfigured CONSTANT)
    Q_PROPERTY(QString connectionState READ connectionState NOTIFY connectionStateChanged)
    Q_PROPERTY(bool online READ online NOTIFY connectionStateChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString lastError READ lastError NOTIFY lastErrorChanged)
    Q_PROPERTY(QString campaignId READ campaignId NOTIFY campaignChanged)
    Q_PROPERTY(QString campaignState READ campaignState NOTIFY campaignChanged)
    Q_PROPERTY(bool terminal READ terminal NOTIFY campaignChanged)
    Q_PROPERTY(bool hasCampaign READ hasCampaign NOTIFY campaignChanged)

public:
    enum Column {
        SequenceColumn = 0,
        EventColumn,
        DetailColumn,
        ColumnCount
    };
    Q_ENUM(Column)

    enum Role {
        DisplayRoleInternal = Qt::DisplayRole,
        SequenceRole = Qt::UserRole + 1,
        EventTypeRole,
        CreatedAtRole,
        DetailRole,
        RecordIdRole,
        PayloadJsonRole,
        ArtifactCountRole
    };
    Q_ENUM(Role)

    explicit RealityCIController(QObject *parent = nullptr);

    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    int columnCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &index, int role = Qt::DisplayRole) const override;
    QHash<int, QByteArray> roleNames() const override;
    QVariant headerData(int section, Qt::Orientation orientation,
                        int role = Qt::DisplayRole) const override;

    int eventCount() const;
    QString baseUrl() const;
    bool tokenConfigured() const;
    QString connectionState() const;
    bool online() const;
    bool busy() const;
    QString lastError() const;
    QString campaignId() const;
    QString campaignState() const;
    bool terminal() const;
    bool hasCampaign() const;

    Q_INVOKABLE void setBaseUrl(const QString &baseUrl);
    Q_INVOKABLE void connectToServer();
    Q_INVOKABLE void createCampaign(const QString &checkpointUri,
                                    int trainingScenarios,
                                    int hiddenExamSize,
                                    int protectedSuiteSize,
                                    int trainingEpochs,
                                    double promotionTarget,
                                    double promotionFloor);
    Q_INVOKABLE void stepCampaign();
    Q_INVOKABLE void runCampaign();
    Q_INVOKABLE void forgetCampaign();
    Q_INVOKABLE void refresh();
    Q_INVOKABLE void clearError();

    Q_INVOKABLE QVariantMap latestPayload(const QString &eventType) const;
    Q_INVOKABLE QVariantList payloadsOf(const QString &eventType) const;
    Q_INVOKABLE QVariantMap campaignRecord() const;
    Q_INVOKABLE QVariantMap eventAt(int row) const;

signals:
    void eventsChanged();
    void baseUrlChanged();
    void connectionStateChanged();
    void busyChanged();
    void lastErrorChanged();
    void campaignChanged();

private:
    struct EventRow {
        qint64 sequence = 0;
        QString recordId;
        QString eventType;
        QString createdAt;
        QString detail;
        QVariantMap payload;
        int artifactCount = 0;
    };

    void setConnectionState(const QString &state);
    void setBusy(bool value);
    void fail(const QString &message);
    void resetCampaign();
    void applyEventsJson(const QJsonDocument &document);
    void applyStateJson(const QJsonObject &object);
    static QString summarize(const QString &eventType, const QVariantMap &payload);

    QNetworkReply *get(const QString &path);
    QNetworkReply *post(const QString &path, const QJsonObject &body);

    QNetworkAccessManager m_network;
    QVector<EventRow> m_events;
    QString m_baseUrl;
    QString m_token;
    QString m_connectionState = QStringLiteral("offline");
    QString m_lastError;
    QString m_campaignId;
    QString m_campaignState = QStringLiteral("unknown");
    bool m_busy = false;
};
