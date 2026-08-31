#include "AuthController.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QHostAddress>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QSet>
#include <QSharedPointer>
#include <QTcpServer>
#include <QTcpSocket>
#include <QUrlQuery>
#include <QUuid>

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

QByteArray httpResponse(int status, const QByteArray &contentType, const QByteArray &body)
{
    const QByteArray reason = status == 200 ? "OK"
        : status == 204 ? "No Content"
        : status == 400 ? "Bad Request"
        : status == 404 ? "Not Found"
        : "Error";
    QByteArray response = "HTTP/1.1 " + QByteArray::number(status) + " " + reason + "\r\n";
    response += "Content-Type: " + contentType + "\r\n";
    response += "Content-Length: " + QByteArray::number(body.size()) + "\r\n";
    response += "Cache-Control: no-store\r\n";
    response += "Connection: close\r\n";
    response += "Cross-Origin-Opener-Policy: same-origin-allow-popups\r\n";
    response += "\r\n";
    response += body;
    return response;
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
bool AuthController::googleSignInAvailable() const { return m_configured && !localMode(); }
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

QString AuthController::beginGoogleSignIn()
{
    if (localMode() || m_busy)
        return {};
    if (!m_configured) {
        m_lastError = QStringLiteral("Firebase authentication is not configured.");
        emit authenticationChanged();
        return {};
    }

    closeGoogleBridge();
    ++m_generation;
    const quint64 generation = m_generation;
    m_googleState = QUuid::createUuid().toString(QUuid::WithoutBraces);
    m_googleServer = new QTcpServer(this);
    if (!m_googleServer->listen(QHostAddress::LocalHost, 0)) {
        m_googleServer->deleteLater();
        m_googleServer = nullptr;
        m_lastError = QStringLiteral("Servo could not start the secure local Google sign-in callback.");
        emit authenticationChanged();
        return {};
    }

    connect(m_googleServer, &QTcpServer::newConnection, this, [this]() {
        while (m_googleServer && m_googleServer->hasPendingConnections()) {
            QTcpSocket *socket = m_googleServer->nextPendingConnection();
            auto buffer = QSharedPointer<QByteArray>::create();
            connect(socket, &QTcpSocket::readyRead, this, [this, socket, buffer]() {
                buffer->append(socket->readAll());
                const qsizetype headersEnd = buffer->indexOf("\r\n\r\n");
                if (headersEnd < 0)
                    return;
                qsizetype contentLength = 0;
                const QList<QByteArray> headers = buffer->left(headersEnd).split('\n');
                for (QByteArray header : headers) {
                    header = header.trimmed();
                    if (header.toLower().startsWith("content-length:"))
                        contentLength = header.mid(15).trimmed().toLongLong();
                }
                if (buffer->size() < headersEnd + 4 + contentLength)
                    return;
                if (socket->property("servoHandled").toBool())
                    return;
                socket->setProperty("servoHandled", true);
                serveGoogleRequest(socket, *buffer);
            });
            connect(socket, &QTcpSocket::disconnected, socket, &QObject::deleteLater);
        }
    });

    m_busy = true;
    m_state = QStringLiteral("google-browser");
    m_lastError.clear();
    m_notice = QStringLiteral("Complete Google sign-in in the browser window.");
    emit authenticationChanged();

    QTimer::singleShot(300000, this, [this, generation]() {
        if (generation != m_generation || !m_googleServer)
            return;
        closeGoogleBridge();
        m_busy = false;
        m_state = QStringLiteral("signed-out");
        m_notice.clear();
        m_lastError = QStringLiteral("Google sign-in timed out. Try again.");
        emit authenticationChanged();
    });

    QUrl url;
    url.setScheme(QStringLiteral("http"));
    url.setHost(QStringLiteral("127.0.0.1"));
    url.setPort(m_googleServer->serverPort());
    url.setPath(QStringLiteral("/"));
    QUrlQuery query;
    query.addQueryItem(QStringLiteral("state"), m_googleState);
    url.setQuery(query);
    return url.toString(QUrl::FullyEncoded);
}

void AuthController::serveGoogleRequest(QTcpSocket *socket, const QByteArray &request)
{
    const qsizetype lineEnd = request.indexOf("\r\n");
    const qsizetype headersEnd = request.indexOf("\r\n\r\n");
    if (lineEnd < 0 || headersEnd < 0) {
        socket->write(httpResponse(400, "text/plain; charset=utf-8", "Malformed request"));
        socket->disconnectFromHost();
        return;
    }

    const QList<QByteArray> requestLine = request.left(lineEnd).split(' ');
    if (requestLine.size() < 2) {
        socket->write(httpResponse(400, "text/plain; charset=utf-8", "Malformed request"));
        socket->disconnectFromHost();
        return;
    }
    const QByteArray method = requestLine.at(0);
    const QUrl url(QStringLiteral("http://127.0.0.1") + QString::fromUtf8(requestLine.at(1)));
    const QUrlQuery query(url);
    const QString state = query.queryItemValue(QStringLiteral("state"));
    if (state != m_googleState || state.isEmpty()) {
        socket->write(httpResponse(400, "text/plain; charset=utf-8", "Invalid sign-in state"));
        socket->disconnectFromHost();
        return;
    }

    if (method == "GET" && url.path() == QStringLiteral("/")) {
        const QJsonObject bridgeConfig{
            {QStringLiteral("apiKey"), m_apiKey},
            {QStringLiteral("authDomain"), m_projectId + QStringLiteral(".firebaseapp.com")},
            {QStringLiteral("projectId"), m_projectId},
            {QStringLiteral("state"), m_googleState},
        };
        const QByteArray config = QJsonDocument(bridgeConfig).toJson(QJsonDocument::Compact);
        QByteArray html = R"HTML(<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in to Servo</title>
<style>
html,body{height:100%;margin:0}body{display:grid;place-items:center;background:#111416;color:#f4f5f5;font:15px system-ui,-apple-system,Segoe UI,sans-serif}.card{width:min(420px,calc(100% - 48px));padding:32px;border:1px solid #34393d;border-radius:16px;background:#1b1f22;box-shadow:0 24px 80px #0008}.brand{font-size:13px;font-weight:700;letter-spacing:.18em}.title{font-size:24px;font-weight:650;margin:28px 0 8px}.copy{color:#aab1b5;line-height:1.5;margin:0 0 24px}button{width:100%;border:0;border-radius:10px;padding:13px 16px;background:#f5f6f6;color:#111416;font:600 15px system-ui;cursor:pointer}button:disabled{opacity:.55;cursor:wait}.status{min-height:20px;margin-top:16px;color:#aab1b5;font-size:13px}.error{color:#ff8170}.security{margin-top:24px;padding-top:18px;border-top:1px solid #30363a;color:#7f898f;font-size:12px;line-height:1.45}
</style></head><body><main class="card"><div class="brand">SERVO</div><div class="title">Continue with Google</div><p class="copy">Firebase will authenticate your Google account, then Servo will verify the resulting identity with its Cloud Run control plane.</p><button id="signIn">Continue with Google</button><div id="status" class="status"></div><div class="security">Your Google password is entered only on Google's page. It is never sent to the Servo desktop app.</div></main>
<script src="https://www.gstatic.com/firebasejs/12.2.1/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/12.2.1/firebase-auth-compat.js"></script>
<script>
const cfg=__SERVO_CONFIG__; const button=document.getElementById('signIn'); const status=document.getElementById('status');
firebase.initializeApp({apiKey:cfg.apiKey,authDomain:cfg.authDomain,projectId:cfg.projectId});
async function report(path,payload){await fetch(path+'?state='+encodeURIComponent(cfg.state),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});}
button.onclick=async()=>{button.disabled=true;status.className='status';status.textContent='Waiting for Google…';try{const result=await firebase.auth().signInWithPopup(new firebase.auth.GoogleAuthProvider());const user=result.user;const idToken=await user.getIdToken(true);await report('/token',{idToken,refreshToken:user.refreshToken||'',email:user.email||'',displayName:user.displayName||'',uid:user.uid||''});status.textContent='Signed in. You can close this window and return to Servo.';button.hidden=true;}catch(error){const code=error&&error.code?error.code:'auth/unknown';const message=error&&error.message?error.message:'Google sign-in failed.';status.className='status error';status.textContent=message;button.disabled=false;try{await report('/error',{code,message});}catch(_){}}};
</script></body></html>)HTML";
        html.replace("__SERVO_CONFIG__", config);
        socket->write(httpResponse(200, "text/html; charset=utf-8", html));
        socket->disconnectFromHost();
        return;
    }

    if (method == "POST" && (url.path() == QStringLiteral("/token")
                              || url.path() == QStringLiteral("/error"))) {
        const QByteArray body = request.mid(headersEnd + 4);
        const QJsonObject object = QJsonDocument::fromJson(body).object();
        const quint64 generation = m_generation;
        if (url.path() == QStringLiteral("/error")) {
            QString message = object.value(QStringLiteral("message")).toString();
            const QString code = object.value(QStringLiteral("code")).toString();
            if (code == QStringLiteral("auth/operation-not-allowed")) {
                message = QStringLiteral(
                    "Google Sign-In is not enabled. In Firebase Console, open Authentication → "
                    "Sign-in method → Google, enable it, choose a support email, and save.");
            } else if (message.isEmpty()) {
                message = QStringLiteral("Google sign-in failed.");
            }
            socket->write(httpResponse(200, "application/json", "{\"received\":true}"));
            socket->disconnectFromHost();
            closeGoogleBridge();
            m_busy = false;
            m_state = QStringLiteral("signed-out");
            m_notice.clear();
            m_lastError = message;
            emit authenticationChanged();
            return;
        }

        const QString idToken = object.value(QStringLiteral("idToken")).toString();
        if (idToken.isEmpty()) {
            socket->write(httpResponse(400, "application/json", "{\"error\":\"missing token\"}"));
            socket->disconnectFromHost();
            return;
        }
        socket->write(httpResponse(200, "application/json", "{\"authenticated\":true}"));
        socket->disconnectFromHost();
        closeGoogleBridge();
        verifyApiSession(
            idToken,
            object.value(QStringLiteral("refreshToken")).toString(),
            3600,
            object.value(QStringLiteral("email")).toString(),
            object.value(QStringLiteral("displayName")).toString(),
            object.value(QStringLiteral("uid")).toString(),
            generation);
        return;
    }

    socket->write(httpResponse(404, "text/plain; charset=utf-8", "Not found"));
    socket->disconnectFromHost();
}

void AuthController::closeGoogleBridge()
{
    if (!m_googleServer)
        return;
    m_googleServer->close();
    m_googleServer->deleteLater();
    m_googleServer = nullptr;
    m_googleState.clear();
}

void AuthController::signOut()
{
    ++m_generation;
    closeGoogleBridge();
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
            if (status == 401 && !firebaseEmailVerified(idToken)) {
                sendVerificationEmail(idToken, generation);
                return;
            }
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
    if (!m_refreshToken.isEmpty())
        m_refreshTimer.start(refreshAfterSeconds * 1000);
    if (tokenChanged)
        emit accessTokenChanged();
    emit authenticationChanged();
}

void AuthController::sendVerificationEmail(const QString &idToken, quint64 generation)
{
    m_state = QStringLiteral("sending-verification");
    emit authenticationChanged();
    QUrl endpoint(QStringLiteral(
        "https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode"));
    QUrlQuery endpointQuery;
    endpointQuery.addQueryItem(QStringLiteral("key"), m_apiKey);
    endpoint.setQuery(endpointQuery);
    QNetworkRequest request(endpoint);
    request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
    const QJsonObject body{
        {QStringLiteral("requestType"), QStringLiteral("VERIFY_EMAIL")},
        {QStringLiteral("idToken"), idToken},
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
        m_lastError.clear();
        if (status >= 200 && status < 300) {
            m_notice = QStringLiteral(
                "Your password is correct, but this account is not verified. Firebase sent a "
                "verification email. Open it, then sign in again.");
        } else {
            m_notice.clear();
            m_lastError = firebaseError(
                payload,
                QStringLiteral(
                    "Your password is correct, but this account is not verified and Firebase "
                    "could not send the verification email."));
        }
        emit authenticationChanged();
    });
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

bool AuthController::firebaseEmailVerified(const QString &idToken)
{
    const QList<QByteArray> sections = idToken.toUtf8().split('.');
    if (sections.size() != 3)
        return false;
    const QByteArray decoded = QByteArray::fromBase64(
        sections.at(1), QByteArray::Base64UrlEncoding | QByteArray::AbortOnBase64DecodingErrors);
    return QJsonDocument::fromJson(decoded)
        .object()
        .value(QStringLiteral("email_verified"))
        .toBool(false);
}
