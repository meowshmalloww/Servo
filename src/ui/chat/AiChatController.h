#pragma once

#include <QAbstractListModel>
#include <QJsonArray>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QPointer>
#include <QStringList>
#include <QTimer>
#include <QUrl>
#include <QVariantList>
#include <QtQmlIntegration>

#include <memory>

class QNetworkReply;
class AiChatStore;

class AiChatController final : public QAbstractListModel
{
    Q_OBJECT
    QML_NAMED_ELEMENT(AiChatController)
    QML_SINGLETON

    Q_PROPERTY(int count READ count NOTIFY countChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(bool configured READ configured CONSTANT)
    Q_PROPERTY(QString statusText READ statusText NOTIFY statusTextChanged)
    Q_PROPERTY(QString errorText READ errorText NOTIFY errorTextChanged)
    Q_PROPERTY(QStringList modelNames READ modelNames CONSTANT)
    Q_PROPERTY(QVariantList modelOptions READ modelOptions CONSTANT)
    Q_PROPERTY(QStringList effortNames READ effortNames CONSTANT)
    Q_PROPERTY(QVariantList pendingAttachments READ pendingAttachments NOTIFY pendingAttachmentsChanged)
    Q_PROPERTY(int maxAttachments READ maxAttachments CONSTANT)

public:
    enum Role {
        AuthorRole = Qt::UserRole + 1,
        ContentRole,
        TimestampRole
    };
    Q_ENUM(Role)

    explicit AiChatController(QObject *parent = nullptr);
    ~AiChatController() override;

    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    int count() const;
    bool busy() const;
    bool configured() const;
    QString statusText() const;
    QString errorText() const;
    QStringList modelNames() const;
    QVariantList modelOptions() const;
    QStringList effortNames() const;
    QVariantList pendingAttachments() const;
    int maxAttachments() const;

    Q_INVOKABLE bool sendMessage(const QString &prompt,
                                 const QString &modelName,
                                 const QString &effortName);
    Q_INVOKABLE bool runLocalAction(const QString &prompt);
    Q_INVOKABLE void recordExternalMessage(const QString &author,
                                           const QString &content);
    Q_INVOKABLE void addAttachments(const QVariantList &urls);
    Q_INVOKABLE void removeAttachment(int index);
    Q_INVOKABLE void clearAttachments();
    Q_INVOKABLE void cancel();
    Q_INVOKABLE void clearConversation();
    Q_INVOKABLE void clearError();

signals:
    void countChanged();
    void busyChanged();
    void statusTextChanged();
    void errorTextChanged();
    void pendingAttachmentsChanged();
    void actionRequested(const QString &action, const QString &argument);

private:
    friend class AiChatControllerTests;

    struct Message {
        QString author;
        QString content;
        QString timestamp;
    };

    struct Attachment {
        QUrl url;
        QString name;
        QString mimeType;
        qint64 size = 0;
    };

    static QString modelId(const QString &modelName);
    static bool isDelayedModel(const QString &modelName);
    static QString effortId(const QString &effortName);
    static QString effectiveEffortId(const QString &modelName, const QString &effortName);
    static QString responseText(const QJsonObject &response);
    static QString delayedResponseText(const QJsonObject &response);
    static QString responseError(const QJsonObject &response);
    static QString cacheKey(const QString &modelId, const QJsonObject &request);

    void appendMessage(const QString &author, const QString &content);
    void setBusy(bool value);
    void setStatusText(const QString &value);
    void setErrorText(const QString &value);
    void finishReply(QNetworkReply *reply);
    void postJson(const QUrl &url, const QJsonObject &payload, int replyKind);
    void pollDelayedJob();
    void resumePendingJob();

    QVector<Message> m_messages;
    QJsonArray m_conversationContents;
    QVector<Attachment> m_attachments;
    QNetworkAccessManager m_network;
    QPointer<QNetworkReply> m_reply;
    QTimer m_pollTimer;
    std::unique_ptr<AiChatStore> m_store;
    QString m_googleApiKey;
    QString m_statusText = QStringLiteral("Ready");
    QString m_errorText;
    QString m_pendingCacheKey;
    QString m_pendingPrompt;
    QString m_pendingModelName;
    QString m_delayedJobName;
    int m_replyKind = 0;
    bool m_vertexExpress = false;
    bool m_busy = false;
};
