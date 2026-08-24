#pragma once

#include <QAbstractListModel>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QPointer>
#include <QStringList>
#include <QUrl>
#include <QVariantList>
#include <QtQmlIntegration>

class QNetworkReply;

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

    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    int count() const;
    bool busy() const;
    bool configured() const;
    QString statusText() const;
    QString errorText() const;
    QStringList modelNames() const;
    QStringList effortNames() const;
    QVariantList pendingAttachments() const;
    int maxAttachments() const;

    Q_INVOKABLE bool sendMessage(const QString &prompt,
                                 const QString &modelName,
                                 const QString &effortName);
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
    static QString effortId(const QString &effortName);
    static QString responseText(const QJsonObject &response);
    static QString responseError(const QJsonObject &response);

    void appendMessage(const QString &author, const QString &content);
    void setBusy(bool value);
    void setStatusText(const QString &value);
    void setErrorText(const QString &value);
    void finishReply(QNetworkReply *reply);

    QVector<Message> m_messages;
    QVector<Attachment> m_attachments;
    QNetworkAccessManager m_network;
    QPointer<QNetworkReply> m_reply;
    QString m_apiKey;
    QString m_statusText = QStringLiteral("Ready");
    QString m_errorText;
    QString m_previousInteractionId;
    QString m_conversationModelId;
    bool m_busy = false;
};
