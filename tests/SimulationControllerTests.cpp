#include "SimulationController.h"
#include "SimulationFrameProvider.h"

#include <QDateTime>
#include <QFile>
#include <QImage>
#include <QJsonArray>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QUrl>
#include <QtTest>

#include <thread>

class SimulationControllerTests final : public QObject
{
    Q_OBJECT

private slots:
    void parsesAuthoritativeLiveState();
    void rejectsOlderSequence();
    void marksOldHeartbeatStale();
    void policyFrameProviderIsThreadSafeAndMonotonic();
    void selectsIntegratedCarlaReplayFromEvidence();
    void keepsExecutionSelectionSeparateFromAttachedSession();
    void clearsStaleAttachedSessionMetadata();
    void reattachesOnlySessionForSelectedExecutionWorld();
};

static QJsonObject pose(double x, double y, double z)
{
    return {
        { QStringLiteral("position"), QJsonObject { { "x", x }, { "y", y }, { "z", z } } },
        { QStringLiteral("orientation"), QJsonObject { { "w", 1.0 }, { "x", 0.0 }, { "y", 0.0 }, { "z", 0.0 } } },
    };
}

static QJsonObject live(quint64 sequence, double speed, const QDateTime &updated)
{
    return {
        { QStringLiteral("sequence"), qint64(sequence) },
        { QStringLiteral("authoritative_frame"), qint64(123 + sequence) },
        { QStringLiteral("simulation_time_s"), 6.15 },
        { QStringLiteral("speed_mps"), speed },
        { QStringLiteral("acceleration_mps2"), 1.25 },
        { QStringLiteral("steering"), -0.2 },
        { QStringLiteral("throttle"), 0.4 },
        { QStringLiteral("brake"), 0.0 },
        { QStringLiteral("target_speed_mps"), 8.0 },
        { QStringLiteral("route_completion"), 0.35 },
        { QStringLiteral("lateral_error_m"), 0.12 },
        { QStringLiteral("renderer_coverage"), 0.91 },
        { QStringLiteral("policy_latency_ms"), 7.5 },
        { QStringLiteral("collision_count"), 0 },
        { QStringLiteral("lane_invasion_count"), 1 },
        { QStringLiteral("deadline_miss_count"), 0 },
        { QStringLiteral("ego_pose_servo"), pose(2.0, 1.0, -4.0) },
        { QStringLiteral("policy_camera_pose_servo"), pose(3.5, 2.4, -4.0) },
        { QStringLiteral("current_result"), QJsonValue::Null },
        { QStringLiteral("last_failure"), QString() },
        { QStringLiteral("policy_frame_id"), 0 },
        { QStringLiteral("wall_clock_updated_at"), updated.toUTC().toString(Qt::ISODateWithMs) },
    };
}

void SimulationControllerTests::parsesAuthoritativeLiveState()
{
    SimulationController controller;
    controller.applyLive(live(5, 4.5, QDateTime::currentDateTimeUtc()));
    QCOMPARE(controller.frameId(), quint64(128));
    QCOMPARE(controller.speedMps(), 4.5);
    QCOMPARE(controller.egoPosition(), QVector3D(2.0f, 1.0f, -4.0f));
    QCOMPARE(controller.egoOrientation(), QQuaternion(1.0f, 0.0f, 0.0f, 0.0f));
    QCOMPARE(controller.policyCameraPosition(), QVector3D(3.5f, 2.4f, -4.0f));
    QVERIFY(!controller.stale());
}

void SimulationControllerTests::rejectsOlderSequence()
{
    SimulationController controller;
    controller.applyLive(live(8, 7.0, QDateTime::currentDateTimeUtc()));
    controller.applyLive(live(7, 99.0, QDateTime::currentDateTimeUtc()));
    QCOMPARE(controller.speedMps(), 7.0);
    QCOMPARE(controller.frameId(), quint64(131));
}

void SimulationControllerTests::marksOldHeartbeatStale()
{
    SimulationController controller;
    controller.applyLive(live(1, 0.0, QDateTime::currentDateTimeUtc().addSecs(-10)));
    QVERIFY(controller.stale());
}

void SimulationControllerTests::policyFrameProviderIsThreadSafeAndMonotonic()
{
    SimulationFrameProvider provider;
    QImage oldFrame(4, 4, QImage::Format_RGB32);
    oldFrame.fill(Qt::red);
    QImage newFrame(4, 4, QImage::Format_RGB32);
    newFrame.fill(Qt::green);
    std::thread publisher([&] {
        provider.publish(newFrame, QStringLiteral("sim-a"), 10);
        provider.publish(oldFrame, QStringLiteral("sim-a"), 9);
    });
    for (int index = 0; index < 32; ++index) {
        QSize size;
        provider.requestImage(QString(), &size, QSize());
    }
    publisher.join();
    const QImage result = provider.requestImage(QString(), nullptr, QSize());
    QCOMPARE(result.pixelColor(0, 0), QColor(Qt::green));
}

void SimulationControllerTests::selectsIntegratedCarlaReplayFromEvidence()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    const QString integrated = temporary.filePath(QStringLiteral("integrated.mp4"));
    QFile file(integrated);
    QVERIFY(file.open(QIODevice::WriteOnly));
    file.write("recorded-carla-evidence");
    file.close();

    SimulationController controller;
    controller.applyEvidence(QJsonObject {
        { QStringLiteral("run_evidence_uri"), temporary.filePath(QStringLiteral("run-evidence.json")) },
        { QStringLiteral("evidence"), QJsonObject {
              { QStringLiteral("outcome"), QStringLiteral("success") },
          } },
        { QStringLiteral("artifact_paths"), QJsonObject {
              { QStringLiteral("evidence/servo-t5-carla-lincoln-fixed.mp4"), integrated },
          } },
    });

    QCOMPARE(controller.result(), QStringLiteral("success"));
    QCOMPARE(controller.replayVideoUrl(), QUrl::fromLocalFile(integrated).toString());
}

void SimulationControllerTests::keepsExecutionSelectionSeparateFromAttachedSession()
{
    SimulationController controller;
    controller.attachSimulationEntry(QJsonObject {
        { QStringLiteral("session_id"), QStringLiteral("sim-0123456789abcdef") },
        { QStringLiteral("world_id"), QStringLiteral("attached-world") },
        { QStringLiteral("route_id"), QStringLiteral("primary") },
        { QStringLiteral("policy_name"), QStringLiteral("DriveMA") },
        { QStringLiteral("observation_source"), QStringLiteral("policy-input") },
        { QStringLiteral("weather"), QStringLiteral("snow") },
        { QStringLiteral("snow_accumulation"), 0.9 },
    });

    controller.refreshWorldExecution(QStringLiteral("inspected-world"));

    QCOMPARE(controller.selectedWorldId(), QStringLiteral("attached-world"));
    QCOMPARE(controller.executionWorldId(), QStringLiteral("inspected-world"));
    QCOMPARE(controller.scenarioWeather(), QStringLiteral("snow"));
    QCOMPARE(controller.scenarioSnowAccumulation(), 0.9);
}

void SimulationControllerTests::clearsStaleAttachedSessionMetadata()
{
    SimulationController controller;
    controller.m_sessionId = QStringLiteral("sim-fedcba9876543210");
    controller.m_sessionState = QStringLiteral("reattaching");
    controller.m_selectedWorldId = QStringLiteral("missing-world");
    controller.m_policyName = QStringLiteral("stale-policy");

    controller.clearAttachedSimulation();

    QVERIFY(!controller.hasSession());
    QCOMPARE(controller.sessionState(), QStringLiteral("none"));
    QVERIFY(controller.selectedWorldId().isEmpty());
    QVERIFY(controller.policyName().isEmpty());
}

void SimulationControllerTests::reattachesOnlySessionForSelectedExecutionWorld()
{
    const QJsonObject rejectedLatest {
        { QStringLiteral("session_id"), QStringLiteral("sim-aaaaaaaaaaaaaaaa") },
        { QStringLiteral("world_id"),
          QStringLiteral("yosemite-t5-all-full-route-review-v2-20260828") },
        { QStringLiteral("state"), QStringLiteral("completed") },
        { QStringLiteral("outcome"), QStringLiteral("success") },
        { QStringLiteral("session_evidence_verified"), true },
    };
    const QJsonObject acceptedOlder {
        { QStringLiteral("session_id"), QStringLiteral("sim-bbbbbbbbbbbbbbbb") },
        { QStringLiteral("world_id"),
          QStringLiteral("yosemite-t5-hybrid-full-route-v1-20260828") },
        { QStringLiteral("state"), QStringLiteral("completed") },
        { QStringLiteral("outcome"), QStringLiteral("success") },
        { QStringLiteral("session_evidence_verified"), true },
    };
    const QJsonArray sessions { rejectedLatest, acceptedOlder };

    const QJsonObject selected = SimulationController::selectSimulationEntry(
        sessions,
        rejectedLatest.value(QStringLiteral("session_id")).toString(),
        acceptedOlder.value(QStringLiteral("world_id")).toString());
    QCOMPARE(selected.value(QStringLiteral("session_id")).toString(),
             acceptedOlder.value(QStringLiteral("session_id")).toString());

    const QJsonObject unavailable = SimulationController::selectSimulationEntry(
        QJsonArray { rejectedLatest },
        rejectedLatest.value(QStringLiteral("session_id")).toString(),
        acceptedOlder.value(QStringLiteral("world_id")).toString());
    QVERIFY(unavailable.isEmpty());

    QJsonObject staleSameWorld = acceptedOlder;
    staleSameWorld.insert(QStringLiteral("session_id"),
                          QStringLiteral("sim-cccccccccccccccc"));
    staleSameWorld.insert(QStringLiteral("session_evidence_verified"), false);
    const QJsonObject migrated = SimulationController::selectSimulationEntry(
        QJsonArray { staleSameWorld, acceptedOlder },
        staleSameWorld.value(QStringLiteral("session_id")).toString(),
        acceptedOlder.value(QStringLiteral("world_id")).toString());
    QCOMPARE(migrated.value(QStringLiteral("session_id")).toString(),
             acceptedOlder.value(QStringLiteral("session_id")).toString());

    const QJsonObject migratedBeforeWorldSelection =
        SimulationController::selectSimulationEntry(
            QJsonArray { rejectedLatest, staleSameWorld, acceptedOlder },
            staleSameWorld.value(QStringLiteral("session_id")).toString(),
            QString());
    QCOMPARE(migratedBeforeWorldSelection.value(QStringLiteral("session_id")).toString(),
             acceptedOlder.value(QStringLiteral("session_id")).toString());
}

QTEST_GUILESS_MAIN(SimulationControllerTests)
#include "SimulationControllerTests.moc"
