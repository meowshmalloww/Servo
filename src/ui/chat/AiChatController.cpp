#include "AiChatController.h"

#include "AiChatStore.h"

#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonValue>
#include <QMimeDatabase>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QSet>

#include <algorithm>
#include <chrono>
#include <utility>

namespace {
constexpr int MaximumAttachments = 6;
constexpr qint64 MaximumAttachmentBytes = 8 * 1024 * 1024;
constexpr qsizetype MaximumRequestBytes = 20 * 1024 * 1024;
constexpr int ReplyNone = 0;
constexpr int ReplyRealtime = 1;
constexpr int ReplyDelayedSubmit = 2;
constexpr int ReplyDelayedPoll = 3;
constexpr int DelayedPollIntervalMs = 30'000;
constexpr auto DeveloperApiRoot = "https://generativelanguage.googleapis.com/v1beta/";
constexpr auto VertexExpressApiRoot = "https://aiplatform.googleapis.com/v1/";
constexpr auto SystemInstruction =
    "You are Servo AI Assistant, a concise engineering copilot for a robotics validation workbench. "
    "Be explicit about uncertainty and never invent project state, sensor evidence, or safety results. "
    "Web browsing and web search are disabled. Do not claim that you searched the web.";

QString valueFromEnvFile(const QString &path, const QStringList &names)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text))
        return {};

    while (!file.atEnd()) {
        QString line = QString::fromUtf8(file.readLine()).trimmed();
        if (line.isEmpty() || line.startsWith(QLatin1Char('#')))
            continue;
        if (line.startsWith(QStringLiteral("export ")))
            line.remove(0, 7);

        const qsizetype separator = line.indexOf(QLatin1Char('='));
        if (separator <= 0)
            continue;
        const QString name = line.left(separator).trimmed();
        if (!names.contains(name))
            continue;

        QString value = line.mid(separator + 1).trimmed();
        if (value.size() >= 2
            && ((value.front() == QLatin1Char('"') && value.back() == QLatin1Char('"'))
                || (value.front() == QLatin1Char('\'') && value.back() == QLatin1Char('\'')))) {
            value = value.mid(1, value.size() - 2);
        }
        if (!value.isEmpty())
            return value;
    }
    return {};
}

QString configuredValue(const QStringList &names)
{
    for (const QString &name : names) {
        const QString value = qEnvironmentVariable(name.toUtf8().constData()).trimmed();
        if (!value.isEmpty())
            return value;
    }

    QStringList candidates;
    const QString explicitPath = qEnvironmentVariable("SERVO_ENV_FILE").trimmed();
    if (!explicitPath.isEmpty())
        candidates.append(explicitPath);
    candidates.append(QDir::current().filePath(QStringLiteral(".env")));
    if (QCoreApplication::instance()) {
        candidates.append(QDir(QCoreApplication::applicationDirPath())
                              .filePath(QStringLiteral(".env")));
    }
#ifdef SERVO_PROJECT_SOURCE_DIR
    candidates.append(QDir(QString::fromUtf8(SERVO_PROJECT_SOURCE_DIR))
                          .filePath(QStringLiteral(".env")));
#endif

    QSet<QString> visited;
    for (const QString &candidate : std::as_const(candidates)) {
        const QString path = QFileInfo(candidate).absoluteFilePath();
        if (visited.contains(path))
            continue;
        visited.insert(path);
        const QString value = valueFromEnvFile(path, names);
        if (!value.isEmpty())
            return value;
    }
    return {};
}

QString configuredGoogleApiKey()
{
    return configuredValue({QStringLiteral("GOOGLE_API_KEY"),
                            QStringLiteral("GEMINI_API_KEY")});
}

bool useVertexExpress(const QString &apiKey)
{
    const QString provider = configuredValue({QStringLiteral("SERVO_GOOGLE_API")}).toLower();
    if (provider == QStringLiteral("developer"))
        return false;
    if (provider == QStringLiteral("vertex"))
        return true;
    return apiKey.startsWith(QStringLiteral("AQ."));
}

QJsonObject textContent(const QString &role, const QString &text)
{
    return QJsonObject{
        {QStringLiteral("role"), role},
        {QStringLiteral("parts"), QJsonArray{
             QJsonObject{{QStringLiteral("text"), text}},
         }},
    };
}

QJsonArray inlineResponses(const QJsonObject &operation)
{
    const QList<QJsonObject> containers{
        operation.value(QStringLiteral("response")).toObject(),
        operation.value(QStringLiteral("dest")).toObject(),
    };
    for (const QJsonObject &container : containers) {
        QJsonArray responses = container.value(QStringLiteral("inlinedResponses")).toArray();
        if (responses.isEmpty())
            responses = container.value(QStringLiteral("inlined_responses")).toArray();
        if (!responses.isEmpty())
            return responses;
    }
    return {};
}
}

AiChatController::AiChatController(QObject *parent)
    : QAbstractListModel(parent)
    , m_store(std::make_unique<AiChatStore>())
    , m_googleApiKey(configuredGoogleApiKey())
    , m_vertexExpress(useVertexExpress(m_googleApiKey))
{
    m_network.setTransferTimeout(std::chrono::minutes(2));
    m_pollTimer.setSingleShot(true);
    m_pollTimer.setInterval(DelayedPollIntervalMs);
    connect(&m_pollTimer, &QTimer::timeout, this, &AiChatController::pollDelayedJob);

    if (!configured())
        m_statusText = QStringLiteral("API key required");
    else
        resumePendingJob();
}

AiChatController::~AiChatController() = default;

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
    return !m_googleApiKey.isEmpty();
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
        QStringLiteral("Gemini 3.6 Flash"),
        QStringLiteral("Gemini 3.7 Long Run"),
        QStringLiteral("Gemini 3.6 Long Run"),
    };
}

QVariantList AiChatController::modelOptions() const
{
    return {
        QVariantMap{
            {QStringLiteral("name"), QStringLiteral("Gemini 3.7 Flash")},
            {QStringLiteral("description"), QStringLiteral("Fast agentic work · Low, Medium, or High thinking")},
            {QStringLiteral("provider"), QStringLiteral("Google")},
            {QStringLiteral("efforts"), QStringList{QStringLiteral("Low"), QStringLiteral("Medium"), QStringLiteral("High")}},
            {QStringLiteral("delayed"), false},
            {QStringLiteral("fixedHigh"), false},
        },
        QVariantMap{
            {QStringLiteral("name"), QStringLiteral("Gemini 3.6 Flash")},
            {QStringLiteral("description"), QStringLiteral("Reliable everyday work · High thinking")},
            {QStringLiteral("provider"), QStringLiteral("Google")},
            {QStringLiteral("efforts"), QStringList{QStringLiteral("High")}},
            {QStringLiteral("delayed"), false},
            {QStringLiteral("fixedHigh"), true},
        },
        QVariantMap{
            {QStringLiteral("name"), QStringLiteral("Gemini 3.7 Long Run")},
            {QStringLiteral("description"), QStringLiteral("Up to 24 hours · Best for long autonomous tasks")},
            {QStringLiteral("provider"), QStringLiteral("Google")},
            {QStringLiteral("efforts"), QStringList{QStringLiteral("Low"), QStringLiteral("Medium"), QStringLiteral("High")}},
            {QStringLiteral("delayed"), true},
            {QStringLiteral("fixedHigh"), false},
        },
        QVariantMap{
            {QStringLiteral("name"), QStringLiteral("Gemini 3.6 Long Run")},
            {QStringLiteral("description"), QStringLiteral("Up to 24 hours · Autonomous tasks with High thinking")},
            {QStringLiteral("provider"), QStringLiteral("Google")},
            {QStringLiteral("efforts"), QStringList{QStringLiteral("High")}},
            {QStringLiteral("delayed"), true},
            {QStringLiteral("fixedHigh"), true},
        },
    };
}

QStringList AiChatController::effortNames() const
{
    return {
        QStringLiteral("Low"),
        QStringLiteral("Medium"),
        QStringLiteral("High"),
        QStringLiteral("XHigh"),
        QStringLiteral("Max"),
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

bool AiChatController::runLocalAction(const QString &prompt)
{
    const QString text = prompt.simplified();
    const QString lower = text.toLower();
    QString action;
    QString argument;
    QString response;

    if ((lower.contains(QStringLiteral("r17"))
         && (lower.contains(QStringLiteral("open"))
             || lower.contains(QStringLiteral("load"))
             || lower.contains(QStringLiteral("explore"))))) {
        action = QStringLiteral("explore-world");
        argument = QStringLiteral("r17");
        response = QStringLiteral("Opening R17 in Gaussian Explore. Use W/S to follow the capture path, A/D for bounded lateral movement, drag to look, and the speed presets in the viewport.");
    } else if (lower.contains(QStringLiteral("snow"))) {
        action = QStringLiteral("weather");
        argument = QStringLiteral("snow");
        response = QStringLiteral("Enabling native snow accumulation. Snow is deposited on inferred up-facing Gaussian surfaces and the physical vehicle, and tyre grip is reduced. The visual snow depth is nonmetric and is not a ClimateNeRF-qualified sensor product.");
    } else if (lower.contains(QStringLiteral("rain"))) {
        action = QStringLiteral("weather");
        argument = QStringLiteral("clear");
        response = QStringLiteral("Rain remains disabled. ClimateNeRF does not implement rain, and Servo no longer provides a synthetic rain preview.");
    } else if (lower.contains(QStringLiteral("fog"))) {
        action = QStringLiteral("weather");
        argument = QStringLiteral("clear");
        response = QStringLiteral("Fog remains disabled. ClimateNeRF provides smog rather than generic fog, and the current T5 smog qualification failed its image-quality gate.");
    } else if (lower.contains(QStringLiteral("flood"))) {
        action = QStringLiteral("weather");
        argument = QStringLiteral("clear");
        response = QStringLiteral("Flood remains disabled. T5 has no metric scale or scene-qualified water plane, so Servo refuses to fabricate flood water.");
    } else if (lower.contains(QStringLiteral("wet"))) {
        action = QStringLiteral("weather");
        argument = QStringLiteral("clear");
        response = QStringLiteral("Wet appearance remains disabled. The former presentation-shader preview was removed and no quality-accepted ClimateNeRF bundle is active.");
    } else if ((lower.contains(QStringLiteral("clear weather"))
                || lower.contains(QStringLiteral("stop weather"))
                || lower == QStringLiteral("clear"))) {
        action = QStringLiteral("weather");
        argument = QStringLiteral("clear");
        response = QStringLiteral("Weather visualization cleared.");
    } else if (lower.contains(QStringLiteral("open runs"))
               || lower.contains(QStringLiteral("show runs"))
               || lower.contains(QStringLiteral("campaign"))) {
        action = QStringLiteral("open-runs");
        response = QStringLiteral("Opening Runs. Servo will show the connected RealityCI campaign and its measured evidence.");
    } else if (lower.contains(QStringLiteral("create world"))
               || lower.contains(QStringLiteral("build world"))) {
        action = QStringLiteral("create-world");
        response = QStringLiteral("Opening Create World. Add source media there; Servo will keep R17 unchanged unless you explicitly build a new world.");
    } else if (lower.contains(QStringLiteral("open world"))
               || lower.contains(QStringLiteral("show world"))) {
        action = QStringLiteral("open-worlds");
        response = QStringLiteral("Opening the world library.");
    } else {
        return false;
    }

    appendMessage(QStringLiteral("user"), text);
    appendMessage(QStringLiteral("assistant"), response);
    setStatusText(QStringLiteral("Action complete"));
    clearError();
    emit actionRequested(action, argument);
    return true;
}

bool AiChatController::sendMessage(const QString &prompt,
                                   const QString &modelName,
                                   const QString &effortName)
{
    const QString trimmed = prompt.trimmed();
    if (trimmed.isEmpty() || m_busy)
        return false;

    if (m_googleApiKey.isEmpty()) {
        setErrorText(QStringLiteral("Set GOOGLE_API_KEY or GEMINI_API_KEY in Servo's .env, then restart the app."));
        return false;
    }

    QJsonArray geminiParts{QJsonObject{{QStringLiteral("text"), trimmed}}};
    for (const Attachment &attachment : std::as_const(m_attachments)) {
        QFile file(attachment.url.toLocalFile());
        if (!file.open(QIODevice::ReadOnly)) {
            setErrorText(QStringLiteral("Unable to read attachment: %1").arg(attachment.name));
            return false;
        }
        const QByteArray encoded = file.readAll().toBase64();
        geminiParts.append(QJsonObject{
            {QStringLiteral("inlineData"), QJsonObject{
                 {QStringLiteral("mimeType"), attachment.mimeType},
                 {QStringLiteral("data"), QString::fromLatin1(encoded)},
             }},
        });
    }

    const QString selectedModelId = modelId(modelName);
    QJsonArray geminiContents = m_conversationContents;
    const QJsonObject geminiUserContent{
        {QStringLiteral("role"), QStringLiteral("user")},
        {QStringLiteral("parts"), geminiParts},
    };
    geminiContents.append(geminiUserContent);

    const QJsonObject geminiRequest{
        {QStringLiteral("systemInstruction"), QJsonObject{
             {QStringLiteral("parts"), QJsonArray{
                  QJsonObject{{QStringLiteral("text"), QString::fromLatin1(SystemInstruction)}},
              }},
         }},
        {QStringLiteral("contents"), geminiContents},
        {QStringLiteral("generationConfig"), QJsonObject{
             {QStringLiteral("thinkingConfig"), QJsonObject{
                  {QStringLiteral("thinkingLevel"), effectiveEffortId(modelName, effortName)},
              }},
         }},
    };

    if (QJsonDocument(geminiRequest).toJson(QJsonDocument::Compact).size()
        > MaximumRequestBytes) {
        setErrorText(QStringLiteral("This request is too large. Remove one or more images."));
        return false;
    }
    const QString requestCacheKey = cacheKey(selectedModelId, geminiRequest);

    appendMessage(QStringLiteral("user"), trimmed);
    m_conversationContents.append(geminiUserContent);
    clearAttachments();
    clearError();

    if (const std::optional<QString> cached = m_store->cachedResponse(requestCacheKey)) {
        appendMessage(QStringLiteral("assistant"), *cached);
        m_conversationContents.append(textContent(QStringLiteral("model"), *cached));
        setStatusText(QStringLiteral("Loaded from local cache"));
        return true;
    }

    m_pendingCacheKey = requestCacheKey;
    m_pendingPrompt = trimmed;
    m_pendingModelName = modelName;
    setBusy(true);

    if (isDelayedModel(modelName)) {
        const QJsonObject payload{
            {QStringLiteral("batch"), QJsonObject{
                 {QStringLiteral("display_name"), QStringLiteral("Servo autonomous run")},
                 {QStringLiteral("input_config"), QJsonObject{
                      {QStringLiteral("requests"), QJsonObject{
                           {QStringLiteral("requests"), QJsonArray{
                                QJsonObject{
                                    {QStringLiteral("request"), geminiRequest},
                                    {QStringLiteral("metadata"), QJsonObject{
                                         {QStringLiteral("key"), requestCacheKey.left(24)},
                                     }},
                                },
                            }},
                       }},
                  }},
             }},
        };
        setStatusText(QStringLiteral("Submitting long run"));
        postJson(QUrl(QString::fromLatin1(DeveloperApiRoot)
                          + QStringLiteral("models/%1:batchGenerateContent").arg(selectedModelId)),
                 payload,
                 ReplyDelayedSubmit);
    } else {
        setStatusText(QStringLiteral("Thinking"));
        const QString endpoint = m_vertexExpress
            ? QString::fromLatin1(VertexExpressApiRoot)
                  + QStringLiteral("publishers/google/models/%1:generateContent").arg(selectedModelId)
            : QString::fromLatin1(DeveloperApiRoot)
                  + QStringLiteral("models/%1:generateContent").arg(selectedModelId);
        postJson(QUrl(endpoint),
                 geminiRequest,
                 ReplyRealtime);
    }
    return true;
}

void AiChatController::recordExternalMessage(const QString &author,
                                             const QString &content)
{
    const QString normalizedAuthor = author == QStringLiteral("user")
        ? QStringLiteral("user") : QStringLiteral("assistant");
    const QString normalizedContent = content.trimmed();
    if (normalizedContent.isEmpty())
        return;
    appendMessage(normalizedAuthor, normalizedContent);
    clearError();
    setStatusText(QStringLiteral("Ready"));
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
    m_pollTimer.stop();
    if (m_reply)
        m_reply->abort();

    if (!m_delayedJobName.isEmpty()) {
        QNetworkRequest request(QUrl(QString::fromLatin1(DeveloperApiRoot)
                                     + m_delayedJobName + QStringLiteral(":cancel")));
        request.setRawHeader("x-goog-api-key", m_googleApiKey.toUtf8());
        QNetworkReply *cancelReply = m_network.post(request, QByteArray());
        connect(cancelReply, &QNetworkReply::finished, cancelReply, &QObject::deleteLater);
        m_store->removePendingJob(m_delayedJobName);
        m_delayedJobName.clear();
    }

    m_replyKind = ReplyNone;
    m_pendingCacheKey.clear();
    m_pendingPrompt.clear();
    m_pendingModelName.clear();
    setBusy(false);
    setStatusText(QStringLiteral("Stopped"));
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
    m_conversationContents = {};
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
    if (modelName.startsWith(QStringLiteral("Gemini 3.6")))
        return QStringLiteral("gemini-3.6-flash");
    return QStringLiteral("gemini-3.7-flash");
}

bool AiChatController::isDelayedModel(const QString &modelName)
{
    return modelName.endsWith(QStringLiteral("Long Run"));
}

QString AiChatController::effortId(const QString &effortName)
{
    if (effortName.compare(QStringLiteral("Low"), Qt::CaseInsensitive) == 0)
        return QStringLiteral("low");
    if (effortName.compare(QStringLiteral("High"), Qt::CaseInsensitive) == 0)
        return QStringLiteral("high");
    if (effortName.compare(QStringLiteral("XHigh"), Qt::CaseInsensitive) == 0)
        return QStringLiteral("xhigh");
    if (effortName.compare(QStringLiteral("Max"), Qt::CaseInsensitive) == 0)
        return QStringLiteral("max");
    return QStringLiteral("medium");
}

QString AiChatController::effectiveEffortId(const QString &modelName,
                                            const QString &effortName)
{
    return modelName.startsWith(QStringLiteral("Gemini 3.6"))
        ? QStringLiteral("high")
        : effortId(effortName);
}

QString AiChatController::responseText(const QJsonObject &response)
{
    QStringList chunks;
    const QJsonArray candidates = response.value(QStringLiteral("candidates")).toArray();
    for (const QJsonValue &candidateValue : candidates) {
        const QJsonArray parts = candidateValue.toObject()
                                     .value(QStringLiteral("content")).toObject()
                                     .value(QStringLiteral("parts")).toArray();
        for (const QJsonValue &partValue : parts) {
            const QString text = partValue.toObject().value(QStringLiteral("text")).toString();
            if (!text.isEmpty())
                chunks.append(text);
        }
    }
    return chunks.join(QString()).trimmed();
}

QString AiChatController::delayedResponseText(const QJsonObject &response)
{
    const QJsonArray responses = inlineResponses(response);
    for (const QJsonValue &value : responses) {
        const QJsonObject item = value.toObject();
        const QString output = responseText(item.value(QStringLiteral("response")).toObject());
        if (!output.isEmpty())
            return output;
    }
    return {};
}

QString AiChatController::responseError(const QJsonObject &response)
{
    const QJsonObject error = response.value(QStringLiteral("error")).toObject();
    const QJsonArray details = error.value(QStringLiteral("details")).toArray();
    for (const QJsonValue &detailValue : details) {
        if (detailValue.toObject().value(QStringLiteral("reason")).toString()
            == QStringLiteral("API_KEY_SERVICE_BLOCKED")) {
            return QStringLiteral(
                "This key can run Vertex AI chat, but Long Run also needs Generative Language API access in the key's API restrictions.");
        }
    }
    const QString message = error.value(QStringLiteral("message")).toString().trimmed();
    return message.isEmpty() ? QStringLiteral("The assistant returned an invalid response.") : message;
}

QString AiChatController::cacheKey(const QString &modelId, const QJsonObject &request)
{
    QByteArray source = modelId.toUtf8();
    source.append('\n');
    source.append(QJsonDocument(request).toJson(QJsonDocument::Compact));
    return QString::fromLatin1(QCryptographicHash::hash(source, QCryptographicHash::Sha256).toHex());
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

void AiChatController::postJson(const QUrl &url, const QJsonObject &payload, int replyKind)
{
    QNetworkRequest request(url);
    request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
    request.setRawHeader("x-goog-api-key", m_googleApiKey.toUtf8());
    request.setRawHeader("User-Agent", "Servo/0.2 Qt/6.11");

    QNetworkReply *reply = m_network.post(
        request, QJsonDocument(payload).toJson(QJsonDocument::Compact));
    m_reply = reply;
    m_replyKind = replyKind;
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        finishReply(reply);
    });
}

void AiChatController::pollDelayedJob()
{
    if (m_delayedJobName.isEmpty() || m_reply)
        return;

    QNetworkRequest request(QUrl(QString::fromLatin1(DeveloperApiRoot) + m_delayedJobName));
    request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
    request.setRawHeader("x-goog-api-key", m_googleApiKey.toUtf8());
    request.setRawHeader("User-Agent", "Servo/0.2 Qt/6.11");

    QNetworkReply *reply = m_network.get(request);
    m_reply = reply;
    m_replyKind = ReplyDelayedPoll;
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        finishReply(reply);
    });
}

void AiChatController::resumePendingJob()
{
    const std::optional<AiChatStore::PendingJob> job = m_store->pendingJob();
    if (!job)
        return;

    m_delayedJobName = job->name;
    m_pendingPrompt = job->prompt;
    m_pendingCacheKey = job->cacheKey;
    m_pendingModelName = job->modelName;
    appendMessage(QStringLiteral("user"), job->prompt);
    m_conversationContents.append(textContent(QStringLiteral("user"), job->prompt));
    setBusy(true);
    setStatusText(QStringLiteral("Resuming long run · may take up to 24 hours"));
    QTimer::singleShot(0, this, &AiChatController::pollDelayedJob);
}

void AiChatController::finishReply(QNetworkReply *reply)
{
    const QByteArray body = reply->readAll();
    const QNetworkReply::NetworkError networkError = reply->error();
    const QString networkErrorText = reply->errorString();
    const bool canceled = networkError == QNetworkReply::OperationCanceledError;
    const QJsonObject response = QJsonDocument::fromJson(body).object();
    const int replyKind = m_replyKind;

    if (m_reply == reply)
        m_reply.clear();
    m_replyKind = ReplyNone;
    reply->deleteLater();

    if (canceled) {
        setBusy(false);
        setStatusText(QStringLiteral("Stopped"));
        return;
    }

    if (networkError != QNetworkReply::NoError) {
        const QString apiError = responseError(response);
        setErrorText(apiError == QStringLiteral("The assistant returned an invalid response.")
                         ? networkErrorText
                         : apiError);
        setBusy(false);
        setStatusText(QStringLiteral("Request failed"));
        return;
    }

    if (replyKind == ReplyDelayedSubmit) {
        m_delayedJobName = response.value(QStringLiteral("name")).toString();
        if (m_delayedJobName.isEmpty()) {
            setErrorText(responseError(response));
            setBusy(false);
            setStatusText(QStringLiteral("Request failed"));
            return;
        }
        m_store->storePendingJob(AiChatStore::PendingJob{
            m_delayedJobName,
            m_pendingPrompt,
            m_pendingCacheKey,
            m_pendingModelName,
        });
        setStatusText(QStringLiteral("Long run queued · may take up to 24 hours"));
        m_pollTimer.start(1'000);
        return;
    }

    if (replyKind == ReplyDelayedPoll) {
        const bool done = response.value(QStringLiteral("done")).toBool(false);
        const QString state = response.value(QStringLiteral("metadata")).toObject()
                                  .value(QStringLiteral("state")).toString();
        if (!done && !state.endsWith(QStringLiteral("FAILED"))
            && !state.endsWith(QStringLiteral("CANCELLED"))
            && !state.endsWith(QStringLiteral("EXPIRED"))) {
            setStatusText(QStringLiteral("Long run in progress · may take up to 24 hours"));
            m_pollTimer.start();
            return;
        }

        const QString output = delayedResponseText(response);
        if (output.isEmpty()) {
            const QJsonObject operationError = response.value(QStringLiteral("error")).toObject();
            const QString message = operationError.value(QStringLiteral("message")).toString();
            setErrorText(message.isEmpty()
                             ? QStringLiteral("The long run finished without a text response.")
                             : message);
            setBusy(false);
            setStatusText(QStringLiteral("Long run failed"));
            m_store->removePendingJob(m_delayedJobName);
            m_delayedJobName.clear();
            return;
        }

        m_store->storeResponse(m_pendingCacheKey, output);
        m_store->removePendingJob(m_delayedJobName);
        m_delayedJobName.clear();
        appendMessage(QStringLiteral("assistant"), output);
        m_conversationContents.append(textContent(QStringLiteral("model"), output));
        setBusy(false);
        setStatusText(QStringLiteral("Long run complete"));
        return;
    }

    const QString output = responseText(response);
    if (output.isEmpty()) {
        setErrorText(responseError(response));
        setBusy(false);
        setStatusText(QStringLiteral("Request failed"));
        return;
    }

    m_store->storeResponse(m_pendingCacheKey, output);
    appendMessage(QStringLiteral("assistant"), output);
    m_conversationContents.append(textContent(QStringLiteral("model"), output));
    setBusy(false);
    setStatusText(QStringLiteral("Ready"));
}
