#pragma once

#include <QObject>
#include <QString>
#include <QTimer>
#include <QtQml/qqmlregistration.h>

class QJsonObject;
class QNetworkAccessManager;

class AuthController final : public QObject
{
    Q_OBJECT
    QML_NAMED_ELEMENT(AuthController)
    QML_SINGLETON

    Q_PROPERTY(QString mode READ mode CONSTANT)
    Q_PROPERTY(bool localMode READ localMode CONSTANT)
    Q_PROPERTY(bool configured READ configured NOTIFY authenticationChanged)
    Q_PROPERTY(bool authenticated READ authenticated NOTIFY authenticationChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY authenticationChanged)
    Q_PROPERTY(QString state READ state NOTIFY authenticationChanged)
    Q_PROPERTY(QString email READ email NOTIFY authenticationChanged)
    Q_PROPERTY(QString displayName READ displayName NOTIFY authenticationChanged)
    Q_PROPERTY(QString userId READ userId NOTIFY authenticationChanged)
    Q_PROPERTY(QString projectId READ projectId CONSTANT)
    Q_PROPERTY(QString apiBaseUrl READ apiBaseUrl CONSTANT)
    Q_PROPERTY(QString lastError READ lastError NOTIFY authenticationChanged)
    // Trusted in-process QML passes this directly to the two API controllers.
    // It is never persisted, printed, or written to Settings.
    Q_PROPERTY(QString accessToken READ accessToken NOTIFY accessTokenChanged)

public:
    explicit AuthController(QObject *parent = nullptr);

    QString mode() const;
    bool localMode() const;
    bool configured() const;
    bool authenticated() const;
    bool busy() const;
    QString state() const;
    QString email() const;
    QString displayName() const;
    QString userId() const;
    QString projectId() const;
    QString apiBaseUrl() const;
    QString lastError() const;
    QString accessToken() const;

    Q_INVOKABLE void signIn(const QString &email, const QString &password);
    Q_INVOKABLE void signOut();

signals:
    void authenticationChanged();
    void accessTokenChanged();

private:
    void refreshIdToken();
    void verifyApiSession(const QString &idToken,
                          const QString &refreshToken,
                          int expiresInSeconds,
                          const QString &fallbackEmail,
                          const QString &fallbackDisplayName,
                          const QString &fallbackUserId,
                          quint64 generation);
    void acceptSession(const QString &idToken,
                       const QString &refreshToken,
                       int expiresInSeconds,
                       const QJsonObject &principal,
                       const QString &fallbackEmail,
                       const QString &fallbackDisplayName,
                       const QString &fallbackUserId);
    void rejectSession(const QString &message, quint64 generation);
    static QString firebaseError(const QByteArray &payload, const QString &fallback);

    QNetworkAccessManager *m_network = nullptr;
    QTimer m_refreshTimer;
    QString m_mode;
    QString m_apiKey;
    QString m_projectId;
    QString m_apiBaseUrl;
    QString m_accessToken;
    QString m_refreshToken;
    QString m_email;
    QString m_displayName;
    QString m_userId;
    QString m_state;
    QString m_lastError;
    bool m_configured = false;
    bool m_authenticated = false;
    bool m_busy = false;
    quint64 m_generation = 0;
};
