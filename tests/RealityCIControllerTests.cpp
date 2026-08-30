#include "RealityCIController.h"

#include <QCoreApplication>
#include <QSettings>
#include <QTemporaryDir>
#include <QtTest>

class RealityCIControllerTests final : public QObject
{
    Q_OBJECT

private slots:
    void initTestCase()
    {
        QVERIFY(m_settingsRoot.isValid());
        QCoreApplication::setOrganizationName(QStringLiteral("ServoTests"));
        QCoreApplication::setApplicationName(QStringLiteral("RealityCIControllerTests"));
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat,
                           QSettings::UserScope,
                           m_settingsRoot.path());
    }

    void cleanup()
    {
        QSettings settings;
        settings.clear();
        settings.sync();
    }

    void restoresCampaignForMatchingApi()
    {
        QSettings settings;
        settings.setValue("realityci/baseUrl", "http://127.0.0.1:8000");
        settings.setValue("realityci/campaignBaseUrl", "http://127.0.0.1:8000");
        settings.setValue("realityci/campaignId", "cam-restorable");
        settings.sync();

        RealityCIController controller;
        QCOMPARE(controller.baseUrl(), QStringLiteral("http://127.0.0.1:8000"));
        QCOMPARE(controller.campaignId(), QStringLiteral("cam-restorable"));
        QCOMPARE(controller.campaignState(), QStringLiteral("restoring"));
        QVERIFY(controller.hasCampaign());

        controller.forgetCampaign();
        QVERIFY(!controller.hasCampaign());
        QCOMPARE(controller.campaignState(), QStringLiteral("unknown"));

        QSettings persisted;
        QVERIFY(!persisted.contains("realityci/campaignId"));
        QVERIFY(!persisted.contains("realityci/campaignBaseUrl"));
    }

    void ignoresCampaignFromDifferentApi()
    {
        QSettings settings;
        settings.setValue("realityci/baseUrl", "http://127.0.0.1:8000");
        settings.setValue("realityci/campaignBaseUrl", "https://example.invalid");
        settings.setValue("realityci/campaignId", "cam-other-server");
        settings.sync();

        RealityCIController controller;
        QVERIFY(!controller.hasCampaign());
        QCOMPARE(controller.campaignState(), QStringLiteral("unknown"));
    }

    void routesOnlyExplicitCampaignPrompts()
    {
        RealityCIController controller;

        QVERIFY(controller.isCampaignPrompt(QStringLiteral("Diagnose the failure in this campaign")));
        QVERIFY(controller.isCampaignPrompt(QStringLiteral("Run the hidden exam")));
        QVERIFY(controller.isCampaignPrompt(QStringLiteral("Select the next weakness")));
        QVERIFY(controller.isCampaignPrompt(QStringLiteral("Cancel the run")));

        QVERIFY(!controller.isCampaignPrompt(QStringLiteral("Explain Gaussian splatting")));
        QVERIFY(!controller.isCampaignPrompt(QStringLiteral("Hello Servo")));
        QVERIFY(!controller.isCampaignPrompt(QString()));
    }

private:
    QTemporaryDir m_settingsRoot;
};

QTEST_MAIN(RealityCIControllerTests)

#include "RealityCIControllerTests.moc"
