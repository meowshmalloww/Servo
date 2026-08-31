#include "AuthController.h"

#include <QTest>

namespace {
struct EnvironmentValue {
    QByteArray name;
    QByteArray value;
    bool existed = false;

    explicit EnvironmentValue(const char *variable)
        : name(variable), value(qgetenv(variable)), existed(qEnvironmentVariableIsSet(variable)) {}
    ~EnvironmentValue() {
        if (existed) qputenv(name.constData(), value);
        else qunsetenv(name.constData());
    }
};
} // namespace

class AuthControllerTests final : public QObject
{
    Q_OBJECT
private slots:
    void localDesktopModePreservesExplicitDevelopmentToken();
    void firebaseModeFailsClosedWhenConfigurationIsMissing();
    void configuredFirebaseModeStartsSignedOut();
};

void AuthControllerTests::localDesktopModePreservesExplicitDevelopmentToken()
{
    EnvironmentValue mode("SERVO_AUTH_MODE"), cloud("K_SERVICE"), token("SERVO_API_TOKEN");
    qputenv("SERVO_AUTH_MODE", "local");
    qunsetenv("K_SERVICE");
    qputenv("SERVO_API_TOKEN", "local-secret");
    AuthController controller;
    QCOMPARE(controller.mode(), QStringLiteral("local"));
    QVERIFY(controller.localMode());
    QVERIFY(controller.configured());
    QVERIFY(controller.authenticated());
    QCOMPARE(controller.accessToken(), QStringLiteral("local-secret"));
}

void AuthControllerTests::firebaseModeFailsClosedWhenConfigurationIsMissing()
{
    EnvironmentValue mode("SERVO_AUTH_MODE"), key("SERVO_FIREBASE_API_KEY");
    EnvironmentValue project("SERVO_FIREBASE_PROJECT_ID"), cloudProject("GOOGLE_CLOUD_PROJECT");
    qputenv("SERVO_AUTH_MODE", "firebase");
    qputenv("SERVO_FIREBASE_API_KEY", "");
    qputenv("SERVO_FIREBASE_PROJECT_ID", "");
    qputenv("GOOGLE_CLOUD_PROJECT", "");
    AuthController controller;
    QVERIFY(!controller.configured());
    QVERIFY(!controller.authenticated());
    QCOMPARE(controller.state(), QStringLiteral("configuration-error"));
    QVERIFY(!controller.lastError().isEmpty());
}

void AuthControllerTests::configuredFirebaseModeStartsSignedOut()
{
    EnvironmentValue mode("SERVO_AUTH_MODE"), key("SERVO_FIREBASE_API_KEY");
    EnvironmentValue project("SERVO_FIREBASE_PROJECT_ID");
    qputenv("SERVO_AUTH_MODE", "firebase");
    qputenv("SERVO_FIREBASE_API_KEY", "public-web-api-key");
    qputenv("SERVO_FIREBASE_PROJECT_ID", "servo-test-project");
    AuthController controller;
    QVERIFY(controller.configured());
    QVERIFY(!controller.authenticated());
    QVERIFY(controller.accessToken().isEmpty());
    QCOMPARE(controller.state(), QStringLiteral("signed-out"));
    QCOMPARE(controller.projectId(), QStringLiteral("servo-test-project"));
}

QTEST_GUILESS_MAIN(AuthControllerTests)
#include "AuthControllerTests.moc"
