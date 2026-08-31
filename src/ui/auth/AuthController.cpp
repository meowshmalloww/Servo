#include "AuthController.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QSet>
#include <QUrlQuery>

#include <utility>

namespace {
QString valueFromEnvFile(const QString &path, const QString &name)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text))
        return {};
    while (!file.atEnd()) {
        QString line = QString::fromUtf8(file.readLine()).trimmed();
        if (line.isEmpty() || line.startsWith(u'#'))
            continue;
        if (line.startsWith(QStringLiteral("export ")))
            line.remove(0, 7);
        const qsizetype separator = line.indexOf(u'=');
        if (separator <= 0 || line.left(separator).trimmed() != name)
            continue;
        QString value = line.mid(separator + 1).trimmed();
        if (value.size() >= 2
            && ((value.front() == u'"' && value.back() == u'"')
                || (value.front() == u'\'' && value.back() == u'\''))) {
            value = value.mid(1, value.size() - 2);
        }
        return value;
    }
    return {};
}

QString configuredValue(const char *variable, const QString &fallback = {})
{
    const QString name = QString::fromUtf8(variable);
    if (qEnvironmentVariableIsSet(variable))
        return qEnvironmentVariable(variable).trimmed();
    QStringList candidates;
    const QString explicitPath = qEnvironmentVariable("SERVO_ENV_FILE").trimmed();
    if (!explicitPath.isEmpty())
        candidates.append(explicitPath);
    candidates.append(QDir::current().filePath(QStringLiteral(".env")));
    if (QCoreApplication::instance())
        candidates.append(QDir(QCoreApplication::applicationDirPath()).filePath(QStringLiteral(".env")));
#ifdef SERVO_PROJECT_SOURCE_DIR
    candidates.append(QDir(QString::fromUtf8(SERVO_PROJECT_SOURCE_DIR)).filePath(QStringLiteral(".env")));
#endif
    QSet<QString> visited;
    for (const QString &candidate : std::as_const(candidates)) {
        const QString path = QFileInfo(candidate).absoluteFilePath();
        if (visited.contains(path))
            continue;
        visited.insert(path);
        const QString value = valueFromEnvFile(path, name).trimmed();
        if (!value.isEmpty())
            return value;
    }
    return fallback;
}

int positiveSeconds(const QJsonValue &value)
{
    bool ok = false;
    const int seconds = value.toVariant().toString().toInt(&ok);
    return ok && seconds > 0 ? seconds : 3600;
}
} // namespace

AuthController::AuthController(QObject *parent)
    : QObject(parent)
    , m_network(new QNetworkAccessManager(this))
{
    m_mode = configuredValue("SERVO_AUTH_MODE").toLower();
    if (m_mode.isEmpty())
        m_mode = qEnvironmentVariableIsSet("K_SERVICE") ? QStringLiteral("firebase")
                                                        : QStringLiteral("local");
    m_apiBaseUrl = configuredValue("SERVO_API_URL", QStringLiteral("http://127.0.0.1:8000"));
    while (m_apiBaseUrl.endsWith(u'/'))
        m_apiBaseUrl.chop(1);

    if (m_mode == QStringLiteral("local")) {
        m_configured = true;
        m_authenticated = true;
        m_state = QStringLiteral("local-development");
        m_displayName = QStringLiteral("Local developer");
        m_userId = QStringLiteral("local-developer");
        m_accessToken = configuredValue("SERVO_API_TOKEN");
    } else if (m_mode == QStringLiteral("firebase")) {
        m_apiKey = configuredValue("SERVO_FIREBASE_API_KEY");
        m_projectId = configuredValue(
            "SERVO_FIREBASE_PROJECT_ID",
            configuredValue("GOOGLE_CLOUD_PROJECT"));
        m_configured = !m_apiKey.isEmpty() && !m_projectId.isEmpty();
        m_state = m_configured ? QStringLiteral("signed-out")
                               : QStringLiteral("configuration-error");
        if (!m_configured) {
            m_lastError = QStringLiteral(
                "Firebase login requires SERVO_FIREBASE_API_KEY and "
                "SERVO_FIREBASE_PROJECT_ID.");
        }
    } else {
        m_state = QStringLiteral("configuration-error");
        m_lastError = QStringLiteral("SERVO_AUTH_MODE must be local or firebase.");
    }

    m_refreshTimer.setSingleShot(true);
    connect(&m_refreshTimer, &QTimer::timeout, this, &AuthController::refreshIdToken);
}

QString AuthController::mode() const { return m_mode; }
bool AuthController::localMode() const { return m_mode == QStringLiteral("local"); }
bool AuthController::configured() const { return m_configured; }
bool AuthController::authenticated() const { return m_authenticated; }
bool AuthController::busy() const { return m_busy; }
QString AuthController::state() const { return m_state; }
QString AuthController::email() const { return m_email; }
QString AuthController::displayName() const { return m_displayName; }
QString AuthController::userId() const { return m_userId; }
QString AuthController::projectId() const { return m_projectId; }
QString AuthController::apiBaseUrl() const { return m_apiBaseUrl; }
QString AuthController::lastError() const { return m_lastError; }
QString AuthController::notice() const { return m_notice; }
QString AuthController::accessToken() const { return m_accessToken; }

void AuthController::signIn(const QString &email, const QString &password)
{
    if (localMode() || m_busy)
        return;
    if (!m_configured) {
        m_lastError = QStringLiteral("Firebase authentication is not configured.");
        emit authenticationChanged();
        return;
    }
    if (email.trimmed().isEmpty() || password.isEmpty()) {
        m_lastError = QStringLiteral("Enter both email and password.");
        emit authenticationChanged();
        return;
    }

    ++m_generation;
    const quint64 generation = m_generation;
    m_busy = true;
    m_state = QStringLiteral("signing-in");
    m_lastError.clear();
    m_notice.clear();
    emit authenticationChanged();

    QUrl endpoint(QStringLiteral(
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"));
    QUrlQuery endpointQuery;
    endpointQuery.addQueryItem(QStringLiteral("key"), m_apiKey);
    endpoint.setQuery(endpointQuery);
    QNetworkRequest request(endpoint);
    request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
    QJsonObject body{
        {QStringLiteral("email"), email.trimmed()},
        {QStringLiteral("password"), password},
        {QStringLiteral("returnSecureToken"), true},
    };
    QNetworkReply *reply = m_network->post(request, QJsonDocument(body).toJson(QJsonDocument::Compact));
    connect(reply, &QNetworkReply::finished, this, [this, reply, generation]() {
        const QByteArray payload = reply->readAll();
        const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        reply->deleteLater();
        if (generation != m_generation)
            return;
        const QJsonObject object = QJsonDocument::fromJson(payload).object();
        const QString idToken = object.value(QStringLiteral("idToken")).toString();
        const QString refreshToken = object.value(QStringLiteral("refreshToken")).toString();
        if (status < 200 || status >= 300 || idToken.isEmpty() || refreshToken.isEmpty()) {
            rejectSession(firebaseError(payload, QStringLiteral("Firebase sign-in failed.")), generation);
            return;
        }
        verifyApiSession(
            idToken,
            refreshToken,
            positiveSeconds(object.value(QStringLiteral("expiresIn"))),
            object.value(QStringLiteral("email")).toString(),
            object.value(QStringLiteral("displayName")).toString(),
            object.value(QStringLiteral("localId")).toString(),
            generation);
    });
}

void AuthController::requestPasswordReset(const QString &email)
{
    if (localMode() || m_busy)
        return;
    if (!m_configured) {
        m_lastError = QStringLiteral("Firebase authentication is not configured.");
        emit authenticationChanged();
        return;
    }
    if (email.trimmed().isEmpty()) {
        m_lastError = QStringLiteral("Enter the Firebase account email first.");
        emit authenticationChanged();
        return;
    }

    ++m_generation;
    const quint64 generation = m_generation;
    m_busy = true;
    m_state = QStringLiteral("sending-reset");
    m_lastError.clear();
    m_notice.clear();
    emit authenticationChanged();

    QUrl endpoint(QStringLiteral(
        "https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode"));
    QUrlQuery endpointQuery;
    endpointQuery.addQueryItem(QStringLiteral("key"), m_apiKey);
    endpoint.setQuery(endpointQuery);
    QNetworkRequest request(endpoint);
    request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
    const QJsonObject body{
        {QStringLiteral("requestType"), QStringLiteral("PASSWORD_RESET")},
        {QStringLiteral("email"), email.trimmed()},
    };
    QNetworkReply *reply = m_network->post(
        request, QJsonDocument(body).toJson(QJsonDocument::Compact));
    connect(reply, &QNetworkReply::finished, this, [this, reply, generation]() {
        const QByteArray payload = reply->readAll();
        const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        reply->deleteLater();
        if (generation != m_generation)
            return;
        m_busy = false;
        m_state = QStringLiteral("signed-out");
        if (status < 200 || status >= 300) {
            m_lastError = firebaseError(
                payload, QStringLiteral("Firebase could not send a password reset email."));
            emit authenticationChanged();
            return;
        }
        m_notice = QStringLiteral(
            "Password reset sent. Check the inbox for this Firebase account.");
        emit authenticationChanged();
    });
}

void AuthController::signOut()
{
    ++m_generation;
    m_refreshTimer.stop();
    const bool tokenChanged = !m_accessToken.isEmpty();
    m_accessToken.clear();
    m_refreshToken.clear();
    m_email.clear();
    m_displayName.clear();
    m_userId.clear();
    m_busy = false;
    m_authenticated = localMode();
    m_state = localMode() ? QStringLiteral("local-development")
                          : QStringLiteral("signed-out");
    m_lastError.clear();
    m_notice.clear();
    if (tokenChanged)
        emit accessTokenChanged();
    emit authenticationChanged();
}

void AuthController::refreshIdToken()
{
    if (!m_authenticated || m_refreshToken.isEmpty() || !m_configured)
        return;
    ++m_generation;
    const quint64 generation = m_generation;
    m_busy = true;
    m_state = QStringLiteral("refreshing");
    emit authenticationChanged();

    QUrl endpoint(QStringLiteral("https://securetoken.googleapis.com/v1/token"));
    QUrlQuery endpointQuery;
    endpointQuery.addQueryItem(QStringLiteral("key"), m_apiKey);
    endpoint.setQuery(endpointQuery);
    QNetworkRequest request(endpoint);
    request.setHeader(
        QNetworkRequest::ContentTypeHeader,
        QStringLiteral("application/x-www-form-urlencoded"));
    QUrlQuery form;
    form.addQueryItem(QStringLiteral("grant_type"), QStringLiteral("refresh_token"));
    form.addQueryItem(QStringLiteral("refresh_token"), m_refreshToken);
    QNetworkReply *reply = m_network->post(request, form.query(QUrl::FullyEncoded).toUtf8());
    connect(reply, &QNetworkReply::finished, this, [this, reply, generation]() {
        const QByteArray payload = reply->readAll();
        const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        reply->deleteLater();
        if (generation != m_generation)
            return;
        const QJsonObject object = QJsonDocument::fromJson(payload).object();
        const QString idToken = object.value(QStringLiteral("id_token")).toString();
        const QString refreshToken = object.value(QStringLiteral("refresh_token")).toString();
        if (status < 200 || status >= 300 || idToken.isEmpty()) {
            rejectSession(firebaseError(payload, QStringLiteral("Firebase session expired.")), generation);
            return;
        }
        verifyApiSession(
            idToken,
            refreshToken.isEmpty() ? m_refreshToken : refreshToken,
            positiveSeconds(object.value(QStringLiteral("expires_in"))),
            m_email,
            m_displayName,
            object.value(QStringLiteral("user_id")).toString(m_userId),
            generation);
    });
}

void AuthController::verifyApiSession(const QString &idToken,
                                      const QString &refreshToken,
                                      int expiresInSeconds,
                                      const QString &fallbackEmail,
                                      const QString &fallbackDisplayName,
                                      const QString &fallbackUserId,
                                      quint64 generation)
{
    m_state = QStringLiteral("verifying");
    emit authenticationChanged();
    QNetworkRequest request(QUrl(m_apiBaseUrl + QStringLiteral("/v1/auth/session")));
    request.setRawHeader("Authorization", QByteArray("Bearer ") + idToken.toUtf8());
    QNetworkReply *reply = m_network->get(request);
    connect(reply, &QNetworkReply::finished, this,
            [this, reply, idToken, refreshToken, expiresInSeconds,
             fallbackEmail, fallbackDisplayName, fallbackUserId, generation]() {
        const QByteArray payload = reply->readAll();
        const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        reply->deleteLater();
        if (generation != m_generation)
            return;
        const QJsonObject object = QJsonDocument::fromJson(payload).object();
        if (status < 200 || status >= 300
            || object.value(QStringLiteral("authenticated")).toBool() != true) {
            rejectSession(
                status == 401
                    ? QStringLiteral("Servo rejected this Firebase account.")
                    : QStringLiteral("Servo could not verify the Firebase session."),
                generation);
            return;
        }
        acceptSession(
            idToken,
            refreshToken,
            expiresInSeconds,
            object.value(QStringLiteral("principal")).toObject(),
            fallbackEmail,
            fallbackDisplayName,
            fallbackUserId);
    });
}

void AuthController::acceptSession(const QString &idToken,
                                   const QString &refreshToken,
                                   int expiresInSeconds,
                                   const QJsonObject &principal,
                                   const QString &fallbackEmail,
                                   const QString &fallbackDisplayName,
                                   const QString &fallbackUserId)
{
    const bool tokenChanged = m_accessToken != idToken;
    m_accessToken = idToken;
    m_refreshToken = refreshToken;
    m_email = principal.value(QStringLiteral("email")).toString(fallbackEmail);
    m_displayName = principal.value(QStringLiteral("display_name")).toString(fallbackDisplayName);
    m_userId = principal.value(QStringLiteral("subject")).toString(fallbackUserId);
    m_authenticated = true;
    m_busy = false;
    m_state = QStringLiteral("authenticated");
    m_lastError.clear();
    m_notice.clear();
    const int refreshAfterSeconds = qMax(60, expiresInSeconds - 300);
    m_refreshTimer.start(refreshAfterSeconds * 1000);
    if (tokenChanged)
        emit accessTokenChanged();
    emit authenticationChanged();
}

void AuthController::rejectSession(const QString &message, quint64 generation)
{
    if (generation != m_generation)
        return;
    m_refreshTimer.stop();
    const bool tokenChanged = !m_accessToken.isEmpty();
    m_accessToken.clear();
    m_refreshToken.clear();
    m_authenticated = false;
    m_busy = false;
    m_state = QStringLiteral("signed-out");
    m_lastError = message;
    m_notice.clear();
    if (tokenChanged)
        emit accessTokenChanged();
    emit authenticationChanged();
}

QString AuthController::firebaseError(const QByteArray &payload, const QString &fallback)
{
    const QJsonObject object = QJsonDocument::fromJson(payload).object();
    QString code = object.value(QStringLiteral("error"))
                       .toObject()
                       .value(QStringLiteral("message"))
                       .toString();
    if (code == QStringLiteral("INVALID_LOGIN_CREDENTIALS")
        || code == QStringLiteral("EMAIL_NOT_FOUND")
        || code == QStringLiteral("INVALID_PASSWORD")) {
        return QStringLiteral("Email or password is incorrect.");
    }
    if (code == QStringLiteral("USER_DISABLED"))
        return QStringLiteral("This Firebase account is disabled.");
    if (code == QStringLiteral("TOO_MANY_ATTEMPTS_TRY_LATER"))
        return QStringLiteral("Too many sign-in attempts. Try again later.");
    return fallback;
}
