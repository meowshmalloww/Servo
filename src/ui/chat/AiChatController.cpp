#include "AiChatController.h"

#include <QDateTime>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonValue>
#include <QMimeDatabase>
#include <QNetworkReply>
#include <QNetworkRequest>

#include <algorithm>
#include <chrono>
#include <utility>

namespace {
constexpr int MaximumAttachments = 6;
constexpr qint64 MaximumAttachmentBytes = 8 * 1024 * 1024;
constexpr auto InteractionsEndpoint = "https://generativelanguage.googleapis.com/v1beta/interactions";
}

AiChatController::AiChatController(QObject *parent)
    : QAbstractListModel(parent)
{
    m_apiKey = qEnvironmentVariable("GOOGLE_API_KEY");
    if (m_apiKey.isEmpty())
        m_apiKey = qEnvironmentVariable("GEMINI_API_KEY");

    m_network.setTransferTimeout(std::chrono::minutes(2));
    if (!configured()) {
        m_statusText = QStringLiteral("API key required");
    }
}

int AiChatController::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : m_messages.size();
}

QVariant AiChatController::data(const QModelIndex &index, int role) const
{
    if (!index.isValid() || index.row() < 0 || index.row() >= m_messages.size())
        return {};

    const Message &message = m_messages.at(index.row());
    switch (role) {
    case AuthorRole:
        return message.author;
    case ContentRole:
        return message.content;
    case TimestampRole:
        return message.timestamp;
    default:
        return {};
    }
}

QHash<int, QByteArray> AiChatController::roleNames() const
{
    return {
        {AuthorRole, "author"},
        {ContentRole, "content"},
        {TimestampRole, "timestamp"},
    };
}

int AiChatController::count() const
{
    return m_messages.size();
}

bool AiChatController::busy() const
{
    return m_busy;
}

bool AiChatController::configured() const
{
    return !m_apiKey.isEmpty();
}

QString AiChatController::statusText() const
{
    return m_statusText;
}

QString AiChatController::errorText() const
{
    return m_errorText;
}

QStringList AiChatController::modelNames() const
{
    return {
        QStringLiteral("Gemini 3.7 Flash"),
        QStringLiteral("Gemini 3.5 Flash"),
        QStringLiteral("Gemini 2.5 Pro"),
    };
}

QStringList AiChatController::effortNames() const
{
    return {
        QStringLiteral("Low"),
        QStringLiteral("Medium"),
        QStringLiteral("High"),
    };
}

QVariantList AiChatController::pendingAttachments() const
{
    QVariantList result;
    result.reserve(m_attachments.size());
    for (const Attachment &attachment : m_attachments) {
        result.append(QVariantMap{
            {QStringLiteral("url"), attachment.url},
            {QStringLiteral("name"), attachment.name},
            {QStringLiteral("mimeType"), attachment.mimeType},
            {QStringLiteral("size"), attachment.size},
        });
    }
    return result;
}

int AiChatController::maxAttachments() const
{
    return MaximumAttachments;
}

bool AiChatController::sendMessage(const QString &prompt,
                                   const QString &modelName,
                                   const QString &effortName)
{
    const QString trimmed = prompt.trimmed();
    if (trimmed.isEmpty() || m_busy)
        return false;

    if (!configured()) {
        setErrorText(QStringLiteral(
            "Set GOOGLE_API_KEY or GEMINI_API_KEY, then restart Servo to enable the assistant."));
        return false;
    }

    QJsonArray inputParts;
    inputParts.append(QJsonObject{
        {QStringLiteral("type"), QStringLiteral("text")},
        {QStringLiteral("text"), trimmed},
    });

    for (const Attachment &attachment : std::as_const(m_attachments)) {
        QFile file(attachment.url.toLocalFile());
        if (!file.open(QIODevice::ReadOnly)) {
            setErrorText(QStringLiteral("Unable to read attachment: %1").arg(attachment.name));
            return false;
        }
        inputParts.append(QJsonObject{
            {QStringLiteral("type"), QStringLiteral("image")},
            {QStringLiteral("data"), QString::fromLatin1(file.readAll().toBase64())},
            {QStringLiteral("mime_type"), attachment.mimeType},
        });
    }

    const QString selectedModelId = modelId(modelName);
    if (m_conversationModelId != selectedModelId) {
        m_previousInteractionId.clear();
        m_conversationModelId = selectedModelId;
    }

    QJsonObject payload{
        {QStringLiteral("model"), selectedModelId},
        {QStringLiteral("input"), inputParts},
        {QStringLiteral("store"), true},
        {QStringLiteral("generation_config"), QJsonObject{
             {QStringLiteral("thinking_level"), effortId(effortName)},
         }},
    };
    if (m_previousInteractionId.isEmpty()) {
        payload.insert(
            QStringLiteral("system_instruction"),
            QStringLiteral(
                "You are Servo Assistant, a concise engineering copilot for a robotics validation workbench. "
                "Be explicit about uncertainty and never invent project state, sensor evidence, or safety results."));
    } else {
        payload.insert(QStringLiteral("previous_interaction_id"), m_previousInteractionId);
    }

    appendMessage(QStringLiteral("user"), trimmed);
    clearAttachments();
    clearError();
    setBusy(true);
    setStatusText(QStringLiteral("Thinking"));

    QNetworkRequest request(QUrl(QString::fromLatin1(InteractionsEndpoint)));
    request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
    request.setRawHeader("x-goog-api-key", m_apiKey.toUtf8());
    request.setRawHeader("User-Agent", "Servo/0.2 Qt/6.11");

    QNetworkReply *reply = m_network.post(request, QJsonDocument(payload).toJson(QJsonDocument::Compact));
    m_reply = reply;
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        finishReply(reply);
    });
    return true;
}

void AiChatController::addAttachments(const QVariantList &urls)
{
    QMimeDatabase mimeDatabase;
    QStringList errors;

    for (const QVariant &value : urls) {
        if (m_attachments.size() >= MaximumAttachments)
            break;

        const QUrl url = value.toUrl();
        const QFileInfo info(url.toLocalFile());
        if (!url.isLocalFile() || !info.isFile()) {
            errors.append(QStringLiteral("Only local image files can be attached."));
            continue;
        }

        const QString mimeType = mimeDatabase.mimeTypeForFile(info).name();
        if (!mimeType.startsWith(QStringLiteral("image/"))) {
            errors.append(QStringLiteral("%1 is not an image.").arg(info.fileName()));
            continue;
        }
        if (info.size() > MaximumAttachmentBytes) {
            errors.append(QStringLiteral("%1 exceeds the 8 MiB attachment limit.").arg(info.fileName()));
            continue;
        }

        const bool duplicate = std::any_of(
            m_attachments.cbegin(), m_attachments.cend(),
            [&url](const Attachment &attachment) { return attachment.url == url; });
        if (duplicate)
            continue;

        m_attachments.append(Attachment{url, info.fileName(), mimeType, info.size()});
    }

    emit pendingAttachmentsChanged();
    if (!errors.isEmpty())
        setErrorText(errors.join(QLatin1Char('\n')));
}

void AiChatController::removeAttachment(int index)
{
    if (index < 0 || index >= m_attachments.size())
        return;
    m_attachments.removeAt(index);
    emit pendingAttachmentsChanged();
}

void AiChatController::clearAttachments()
{
    if (m_attachments.isEmpty())
        return;
    m_attachments.clear();
    emit pendingAttachmentsChanged();
}

void AiChatController::cancel()
{
    if (m_reply)
        m_reply->abort();
}

void AiChatController::clearConversation()
{
    cancel();
    if (!m_messages.isEmpty()) {
        beginResetModel();
        m_messages.clear();
        endResetModel();
        emit countChanged();
    }
    m_previousInteractionId.clear();
    m_conversationModelId.clear();
    clearAttachments();
    clearError();
    setStatusText(configured() ? QStringLiteral("Ready") : QStringLiteral("API key required"));
}

void AiChatController::clearError()
{
    setErrorText({});
}

QString AiChatController::modelId(const QString &modelName)
{
    if (modelName == QStringLiteral("Gemini 3.5 Flash"))
        return QStringLiteral("gemini-3.5-flash");
    if (modelName == QStringLiteral("Gemini 2.5 Pro"))
        return QStringLiteral("gemini-2.5-pro");
    return QStringLiteral("gemini-3.7-flash");
}

QString AiChatController::effortId(const QString &effortName)
{
    if (effortName.compare(QStringLiteral("Low"), Qt::CaseInsensitive) == 0)
        return QStringLiteral("low");
    if (effortName.compare(QStringLiteral("High"), Qt::CaseInsensitive) == 0)
        return QStringLiteral("high");
    return QStringLiteral("medium");
}

QString AiChatController::responseText(const QJsonObject &response)
{
    QStringList chunks;
    const QJsonArray steps = response.value(QStringLiteral("steps")).toArray();
    for (const QJsonValue &stepValue : steps) {
        const QJsonObject step = stepValue.toObject();
        if (step.value(QStringLiteral("type")).toString() != QStringLiteral("model_output"))
            continue;
        for (const QJsonValue &contentValue : step.value(QStringLiteral("content")).toArray()) {
            const QJsonObject content = contentValue.toObject();
            if (content.value(QStringLiteral("type")).toString() == QStringLiteral("text"))
                chunks.append(content.value(QStringLiteral("text")).toString());
        }
    }
    return chunks.join(QString()).trimmed();
}

QString AiChatController::responseError(const QJsonObject &response)
{
    const QJsonObject error = response.value(QStringLiteral("error")).toObject();
    const QString message = error.value(QStringLiteral("message")).toString().trimmed();
    return message.isEmpty() ? QStringLiteral("The assistant returned an invalid response.") : message;
}

void AiChatController::appendMessage(const QString &author, const QString &content)
{
    const int row = m_messages.size();
    beginInsertRows({}, row, row);
    m_messages.append(Message{
        author,
        content,
        QDateTime::currentDateTime().toString(QStringLiteral("h:mm AP")),
    });
    endInsertRows();
    emit countChanged();
}

void AiChatController::setBusy(bool value)
{
    if (m_busy == value)
        return;
    m_busy = value;
    emit busyChanged();
}

void AiChatController::setStatusText(const QString &value)
{
    if (m_statusText == value)
        return;
    m_statusText = value;
    emit statusTextChanged();
}

void AiChatController::setErrorText(const QString &value)
{
    if (m_errorText == value)
        return;
    m_errorText = value;
    emit errorTextChanged();
}

void AiChatController::finishReply(QNetworkReply *reply)
{
    const QByteArray body = reply->readAll();
    const QNetworkReply::NetworkError networkError = reply->error();
    const QString networkErrorText = reply->errorString();
    const bool canceled = networkError == QNetworkReply::OperationCanceledError;
    const QJsonDocument document = QJsonDocument::fromJson(body);
    const QJsonObject response = document.object();

    if (m_reply == reply)
        m_reply.clear();
    reply->deleteLater();
    setBusy(false);

    if (canceled) {
        setStatusText(QStringLiteral("Stopped"));
        return;
    }

    if (networkError != QNetworkReply::NoError) {
        const QString apiError = responseError(response);
        setErrorText(apiError == QStringLiteral("The assistant returned an invalid response.")
                         ? networkErrorText
                         : apiError);
        setStatusText(QStringLiteral("Request failed"));
        return;
    }

    const QString output = responseText(response);
    if (output.isEmpty()) {
        setErrorText(responseError(response));
        setStatusText(QStringLiteral("Request failed"));
        return;
    }

    m_previousInteractionId = response.value(QStringLiteral("id")).toString();
    appendMessage(QStringLiteral("assistant"), output);
    setStatusText(QStringLiteral("Ready"));
}
