#include "AiChatController.h"

#include <QJsonArray>
#include <QJsonObject>
#include <QtTest>

class AiChatControllerTests final : public QObject
{
    Q_OBJECT

private slots:
    void mapsModelsAndEffort();
    void extractsTextFromModelOutputSteps();
    void extractsApiError();
};

void AiChatControllerTests::mapsModelsAndEffort()
{
    QCOMPARE(AiChatController::modelId(QStringLiteral("Gemini 3.7 Flash")),
             QStringLiteral("gemini-3.7-flash"));
    QCOMPARE(AiChatController::modelId(QStringLiteral("Gemini 2.5 Pro")),
             QStringLiteral("gemini-2.5-pro"));
    QCOMPARE(AiChatController::effortId(QStringLiteral("Low")), QStringLiteral("low"));
    QCOMPARE(AiChatController::effortId(QStringLiteral("High")), QStringLiteral("high"));
}

void AiChatControllerTests::extractsTextFromModelOutputSteps()
{
    const QJsonObject response{
        {QStringLiteral("steps"), QJsonArray{
             QJsonObject{
                 {QStringLiteral("type"), QStringLiteral("model_output")},
                 {QStringLiteral("content"), QJsonArray{
                      QJsonObject{
                          {QStringLiteral("type"), QStringLiteral("text")},
                          {QStringLiteral("text"), QStringLiteral("First ")},
                      },
                      QJsonObject{
                          {QStringLiteral("type"), QStringLiteral("text")},
                          {QStringLiteral("text"), QStringLiteral("answer")},
                      },
                  }},
             },
         }},
    };

    QCOMPARE(AiChatController::responseText(response), QStringLiteral("First answer"));
}

void AiChatControllerTests::extractsApiError()
{
    const QJsonObject response{
        {QStringLiteral("error"), QJsonObject{
             {QStringLiteral("message"), QStringLiteral("Invalid API key")},
         }},
    };

    QCOMPARE(AiChatController::responseError(response), QStringLiteral("Invalid API key"));
}

QTEST_GUILESS_MAIN(AiChatControllerTests)

#include "AiChatControllerTests.moc"
