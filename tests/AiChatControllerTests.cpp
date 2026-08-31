#include "AiChatController.h"
#include "AiChatStore.h"

#include <QDateTime>
#include <QJsonArray>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QtTest>

class AiChatControllerTests final : public QObject
{
    Q_OBJECT

private slots:
    void mapsModelsAndEffort();
    void extractsGenerateContentText();
    void extractsDelayedText();
    void persistsLocalResponsesAndJobs();
    void dispatchesLocalWorldActions();
    void recordsVerifiedControlPlaneMessages();
    void extractsApiError();
    void liveVertexRequest();
};

void AiChatControllerTests::dispatchesLocalWorldActions()
{
    AiChatController controller;
    QSignalSpy actionSpy(&controller, &AiChatController::actionRequested);

    QVERIFY(controller.runLocalAction(QStringLiteral("Open and explore R17")));
    QCOMPARE(actionSpy.count(), 1);
    QCOMPARE(actionSpy.first().at(0).toString(), QStringLiteral("explore-world"));
    QCOMPARE(actionSpy.first().at(1).toString(), QStringLiteral("r17"));
    QCOMPARE(controller.count(), 2);

    QVERIFY(controller.runLocalAction(QStringLiteral("enable snow accumulation")));
    QCOMPARE(actionSpy.count(), 2);
    QCOMPARE(actionSpy.last().at(0).toString(), QStringLiteral("weather"));
    QCOMPARE(actionSpy.last().at(1).toString(), QStringLiteral("snow"));

    QVERIFY(controller.runLocalAction(QStringLiteral("show rain")));
    QCOMPARE(actionSpy.count(), 3);
    QCOMPARE(actionSpy.last().at(0).toString(), QStringLiteral("weather"));
    QCOMPARE(actionSpy.last().at(1).toString(), QStringLiteral("clear"));
    QVERIFY(controller.runLocalAction(QStringLiteral("show flood water")));
    QCOMPARE(actionSpy.last().at(0).toString(), QStringLiteral("weather"));
    QCOMPARE(actionSpy.last().at(1).toString(), QStringLiteral("clear"));
    QVERIFY(controller.runLocalAction(QStringLiteral("add fog")));
    QCOMPARE(actionSpy.last().at(1).toString(), QStringLiteral("clear"));
    QVERIFY(controller.runLocalAction(QStringLiteral("make the road wet")));
    QCOMPARE(actionSpy.last().at(1).toString(), QStringLiteral("clear"));
    QVERIFY(!controller.runLocalAction(QStringLiteral("explain depth ambiguity")));
}

void AiChatControllerTests::recordsVerifiedControlPlaneMessages()
{
    AiChatController controller;
    controller.recordExternalMessage(QStringLiteral("user"), QStringLiteral("List worlds"));
    controller.recordExternalMessage(QStringLiteral("assistant"), QStringLiteral("Found 24 worlds."));
    QCOMPARE(controller.count(), 2);
    QCOMPARE(controller.data(controller.index(0), AiChatController::AuthorRole).toString(),
             QStringLiteral("user"));
    QCOMPARE(controller.data(controller.index(1), AiChatController::ContentRole).toString(),
             QStringLiteral("Found 24 worlds."));
}

void AiChatControllerTests::mapsModelsAndEffort()
{
    QCOMPARE(AiChatController::modelId(QStringLiteral("Gemini 3.7 Flash")),
             QStringLiteral("gemini-3.7-flash"));
    QCOMPARE(AiChatController::modelId(QStringLiteral("Gemini 3.6 Flash")),
             QStringLiteral("gemini-3.6-flash"));
    QCOMPARE(AiChatController::modelId(QStringLiteral("Gemini 3.7 Long Run")),
             QStringLiteral("gemini-3.7-flash"));
    QCOMPARE(AiChatController::modelId(QStringLiteral("Gemini 3.6 Long Run")),
             QStringLiteral("gemini-3.6-flash"));
    const QStringList models = AiChatController().modelNames();
    QCOMPARE(models.size(), 4);
    QVERIFY(!models.contains(QStringLiteral("Gemini 3.5 Flash")));

    QCOMPARE(AiChatController::effortId(QStringLiteral("Low")), QStringLiteral("low"));
    QCOMPARE(AiChatController::effortId(QStringLiteral("High")), QStringLiteral("high"));
    QCOMPARE(AiChatController::effortId(QStringLiteral("XHigh")), QStringLiteral("xhigh"));
    QCOMPARE(AiChatController::effortId(QStringLiteral("Max")), QStringLiteral("max"));
    QCOMPARE(AiChatController::effectiveEffortId(QStringLiteral("Gemini 3.6 Flash"),
                                                 QStringLiteral("Low")),
             QStringLiteral("high"));
    QCOMPARE(AiChatController::effectiveEffortId(QStringLiteral("Gemini 3.7 Flash"),
                                                 QStringLiteral("Medium")),
             QStringLiteral("medium"));
    QVERIFY(AiChatController::isDelayedModel(QStringLiteral("Gemini 3.7 Long Run")));
    QVERIFY(!AiChatController::isDelayedModel(QStringLiteral("Gemini 3.7 Flash")));
    const QVariantList options = AiChatController().modelOptions();
    QCOMPARE(options.at(1).toMap().value(QStringLiteral("efforts")).toStringList(),
             QStringList{QStringLiteral("High")});
    QCOMPARE(options.size(), 4);
}

void AiChatControllerTests::extractsGenerateContentText()
{
    const QJsonObject response{
        {QStringLiteral("candidates"), QJsonArray{
             QJsonObject{
                 {QStringLiteral("content"), QJsonObject{
                      {QStringLiteral("parts"), QJsonArray{
                           QJsonObject{{QStringLiteral("text"), QStringLiteral("First ")}},
                           QJsonObject{{QStringLiteral("text"), QStringLiteral("answer")}},
                       }},
                  }},
             },
         }},
    };

    QCOMPARE(AiChatController::responseText(response), QStringLiteral("First answer"));
}

void AiChatControllerTests::extractsDelayedText()
{
    const QJsonObject response{
        {QStringLiteral("done"), true},
        {QStringLiteral("response"), QJsonObject{
             {QStringLiteral("inlinedResponses"), QJsonArray{
                  QJsonObject{
                      {QStringLiteral("response"), QJsonObject{
                           {QStringLiteral("candidates"), QJsonArray{
                                QJsonObject{
                                    {QStringLiteral("content"), QJsonObject{
                                         {QStringLiteral("parts"), QJsonArray{
                                              QJsonObject{{QStringLiteral("text"), QStringLiteral("Finished")}},
                                          }},
                                     }},
                                },
                            }},
                       }},
                  },
              }},
         }},
    };

    QCOMPARE(AiChatController::delayedResponseText(response), QStringLiteral("Finished"));
}

void AiChatControllerTests::persistsLocalResponsesAndJobs()
{
    QTemporaryDir directory;
    QVERIFY(directory.isValid());
    const QString path = directory.filePath(QStringLiteral("chat.sqlite3"));

    {
        AiChatStore store(path);
        QVERIFY(store.isOpen());
        store.storeResponse(QStringLiteral("cache-key"), QStringLiteral("cached response"));
        store.storePendingJob({QStringLiteral("batches/123"),
                               QStringLiteral("prompt"),
                               QStringLiteral("cache-key"),
                               QStringLiteral("Gemini 3.7 Long Run")});
    }

    AiChatStore reopened(path);
    QCOMPARE(reopened.cachedResponse(QStringLiteral("cache-key")),
             std::optional<QString>(QStringLiteral("cached response")));
    const std::optional<AiChatStore::PendingJob> job = reopened.pendingJob();
    QVERIFY(job.has_value());
    QCOMPARE(job->name, QStringLiteral("batches/123"));
    reopened.removePendingJob(job->name);
    QVERIFY(!reopened.pendingJob().has_value());
}

void AiChatControllerTests::extractsApiError()
{
    const QJsonObject response{
        {QStringLiteral("error"), QJsonObject{
             {QStringLiteral("message"), QStringLiteral("Invalid API key")},
         }},
    };

    QCOMPARE(AiChatController::responseError(response), QStringLiteral("Invalid API key"));

    const QJsonObject restrictedResponse{
        {QStringLiteral("error"), QJsonObject{
             {QStringLiteral("details"), QJsonArray{
                  QJsonObject{{QStringLiteral("reason"),
                               QStringLiteral("API_KEY_SERVICE_BLOCKED")}},
              }},
         }},
    };
    QVERIFY(AiChatController::responseError(restrictedResponse)
                .contains(QStringLiteral("Generative Language API")));
}

void AiChatControllerTests::liveVertexRequest()
{
    if (qEnvironmentVariableIntValue("SERVO_RUN_LIVE_AI_TEST") != 1)
        QSKIP("Set SERVO_RUN_LIVE_AI_TEST=1 to exercise the configured Vertex API key.");

    AiChatController controller;
    QVERIFY(controller.configured());
    const QString prompt = QStringLiteral("Reply with exactly SERVO_CPP_OK. Request nonce: %1")
                               .arg(QDateTime::currentMSecsSinceEpoch());
    QVERIFY(controller.sendMessage(prompt,
                                   QStringLiteral("Gemini 3.7 Flash"),
                                   QStringLiteral("Low")));
    QTRY_VERIFY_WITH_TIMEOUT(!controller.busy(), 30'000);
    QCOMPARE(controller.errorText(), QString());
    QCOMPARE(controller.rowCount(), 2);
    QVERIFY(controller.data(controller.index(1), AiChatController::ContentRole)
                .toString().contains(QStringLiteral("SERVO_CPP_OK")));
}

QTEST_GUILESS_MAIN(AiChatControllerTests)

#include "AiChatControllerTests.moc"
