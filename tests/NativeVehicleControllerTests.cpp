#include "NativeVehicleController.h"

#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QtTest>

#include <cmath>

class NativeVehicleControllerTests final : public QObject
{
    Q_OBJECT

private slots:
    void loadsFiniteRoadAndMovesUnderWheelForces();
    void gravityDropIsNotHeldByAnInvisibleFloor();
    void driveCameraFacesTheLoadedRoad();
    void synchronizedDriverCameraFacesTheLoadedRoad();
    void autoDriveFollowsDescriptorAndStopsAtFiniteEnd();
    void snowAccumulationChangesThePhysicalGripBudget();

private:
    static QString createWorld(const QString &root,
                               double metersPerWorldUnit = 100.0,
                               bool curved = false);
    static bool writeJson(const QString &path, const QJsonObject &object);
};

bool NativeVehicleControllerTests::writeJson(const QString &path, const QJsonObject &object)
{
    QDir().mkpath(QFileInfo(path).absolutePath());
    QFile file(path);
    return file.open(QIODevice::WriteOnly)
           && file.write(QJsonDocument(object).toJson(QJsonDocument::Indented)) > 0;
}

QString NativeVehicleControllerTests::createWorld(const QString &root,
                                                   double metersPerWorldUnit,
                                                   bool curved)
{
    const QString physicsRoot = QDir(root).filePath(QStringLiteral("physics/native-t5-v1"));
    const QJsonArray centers = curved
        ? QJsonArray {
              QJsonArray { 0.0, 0.0, 0.0 }, QJsonArray { 0.0, 0.0, 0.5 },
              QJsonArray { 0.02, 0.0, 1.0 }, QJsonArray { 0.08, 0.0, 1.5 },
              QJsonArray { 0.18, 0.0, 2.0 }, QJsonArray { 0.33, 0.0, 2.5 },
              QJsonArray { 0.53, 0.0, 3.0 },
          }
        : QJsonArray {
              QJsonArray { 0.0, 0.0, 0.0 }, QJsonArray { 0.0, 0.0, 1.0 },
              QJsonArray { 0.0, 0.0, 2.0 }, QJsonArray { 0.0, 0.0, 3.0 },
          };
    const QJsonArray arcLengths = curved
        ? QJsonArray { 0.0, 0.5, 1.0004, 1.0040 + 0.5, 2.0139, 2.5359, 3.0744 }
        : QJsonArray { 0.0, 1.0, 2.0, 3.0 };
    QJsonArray zeros;
    for (qsizetype index = 0; index < arcLengths.size(); ++index)
        zeros.append(0.0);
    const QJsonObject road {
        { QStringLiteral("schema"), QStringLiteral("servo.road-surface/v1") },
        { QStringLiteral("pathFrame"), QJsonObject {
              { QStringLiteral("origin"), QJsonArray { 0.0, 0.0, 0.0 } },
              { QStringLiteral("up"), QJsonArray { 0.0, 1.0, 0.0 } },
              { QStringLiteral("centers"), centers },
              { QStringLiteral("arcLengths"), arcLengths },
          } },
        { QStringLiteral("surface"), QJsonObject {
              { QStringLiteral("knots"), arcLengths },
              { QStringLiteral("elevations"), zeros },
              { QStringLiteral("banks"), zeros },
              { QStringLiteral("lateralMin"), curved ? -0.55 : -0.05 },
              { QStringLiteral("lateralMax"), curved ? 0.55 : 0.05 },
              { QStringLiteral("lateralOrigin"), 0.0 },
          } },
    };
    const QString roadPath = QDir(physicsRoot).filePath(QStringLiteral("road-surface.json"));
    if (!writeJson(roadPath, road))
        return {};
    const QJsonObject descriptor {
        { QStringLiteral("schema"), QStringLiteral("servo.native-gaussian-vehicle-physics/v1") },
        { QStringLiteral("worldId"), QStringLiteral("native-test-world") },
        { QStringLiteral("roadSurface"), QStringLiteral("road-surface.json") },
        { QStringLiteral("gravityMetersPerSecondSquared"), 9.80665 },
        { QStringLiteral("siScale"), QJsonObject {
              { QStringLiteral("metersPerWorldUnit"), metersPerWorldUnit },
          } },
        { QStringLiteral("vehicle"), QJsonObject {} },
    };
    const QString descriptorRelative = QStringLiteral("physics/native-t5-v1/native-vehicle-physics.json");
    if (!writeJson(QDir(root).filePath(descriptorRelative), descriptor))
        return {};
    const QJsonObject manifest {
        { QStringLiteral("schema"), QStringLiteral("servo.gaussian-world/v1") },
        { QStringLiteral("worldId"), QStringLiteral("native-test-world") },
        { QStringLiteral("physics"), QJsonObject {
              { QStringLiteral("schema"), QStringLiteral("servo.native-gaussian-vehicle-physics/v1") },
              { QStringLiteral("ready"), true },
              { QStringLiteral("carla"), false },
              { QStringLiteral("descriptor"), descriptorRelative },
          } },
    };
    return writeJson(QDir(root).filePath(QStringLiteral("world.json")), manifest) ? root : QString();
}

void NativeVehicleControllerTests::loadsFiniteRoadAndMovesUnderWheelForces()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    const QString world = createWorld(temporary.path());
    QVERIFY(!world.isEmpty());
    NativeVehicleController controller;
    QVERIFY2(controller.loadWorld(world), qPrintable(controller.errorString()));
    QVERIFY(controller.ready());
    QCOMPARE(controller.worldId(), QStringLiteral("native-test-world"));
    QCOMPARE(controller.gravityMetersPerSecondSquared(), 9.80665);
    controller.start();
    controller.setInput(QStringLiteral("forward"), true);
    QTest::qWait(850);
    controller.setInput(QStringLiteral("forward"), false);
    QVERIFY2(controller.wheelContacts() >= 2, qPrintable(controller.status()));
    QVERIFY(controller.speedMps() > 0.05);
}

void NativeVehicleControllerTests::gravityDropIsNotHeldByAnInvisibleFloor()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    NativeVehicleController controller;
    QVERIFY(controller.loadWorld(createWorld(temporary.path())));
    controller.dropFromHeight(8.0);
    const float initialHeight = controller.vehiclePosition().y();
    QTest::qWait(240);
    QVERIFY(controller.falling());
    QVERIFY(controller.vehiclePosition().y() < initialHeight - 0.0005f);
    QCOMPARE(controller.wheelContacts(), 0);
}

void NativeVehicleControllerTests::driveCameraFacesTheLoadedRoad()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    NativeVehicleController controller;
    QVERIFY(controller.loadWorld(createWorld(temporary.path())));
    controller.setCameraMode(1);

    const QVector3D renderedForward = controller.cameraOrientation().rotatedVector(
        QVector3D(0.0f, 0.0f, -1.0f));
    const QVector3D towardVehicle = (controller.vehiclePosition()
                                     - controller.cameraPosition()).normalized();
    QVERIFY2(QVector3D::dotProduct(renderedForward, towardVehicle) > 0.95f,
             "The external Gaussian camera must look toward the physical vehicle/road.");
}

void NativeVehicleControllerTests::synchronizedDriverCameraFacesTheLoadedRoad()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    NativeVehicleController controller;
    QVERIFY(controller.loadWorld(createWorld(temporary.path(), 5.0, true)));
    controller.setCameraMode(1);

    const QVector3D driverForward = controller.driverCameraOrientation().rotatedVector(
        QVector3D(0.0f, 0.0f, -1.0f));
    QVERIFY(std::isfinite(driverForward.x()));
    QVERIFY(std::isfinite(driverForward.y()));
    QVERIFY(std::isfinite(driverForward.z()));
    QVERIFY2(driverForward.lengthSquared() > 0.99f,
             "The synchronized Driver view must publish a normalized camera orientation.");
    QVERIFY2(QVector3D::dotProduct(driverForward, QVector3D(0.0f, 0.0f, 1.0f)) > 0.75f,
             "The synchronized Driver camera must face forward along the loaded road evidence.");
}

void NativeVehicleControllerTests::autoDriveFollowsDescriptorAndStopsAtFiniteEnd()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    NativeVehicleController controller;
    QVERIFY2(controller.loadWorld(createWorld(temporary.path(), 5.0, true)),
             qPrintable(controller.errorString()));
    QVERIFY(controller.autoDriveEnabled());
    controller.start();

    QElapsedTimer timeout;
    timeout.start();
    while (!controller.routeEnded() && timeout.elapsed() < 7000)
        QTest::qWait(40);

    QVERIFY2(controller.routeEnded(), qPrintable(controller.status()));
    QVERIFY(controller.routeCompletion() > 0.55);
    QVERIFY(std::abs(controller.lateralErrorM()) < 1.5);
    QVERIFY(controller.wheelContacts() >= 2);
    QTest::qWait(350);
    QVERIFY(std::abs(controller.speedMps()) < 0.75);
    QCOMPARE(controller.status(), QStringLiteral("Route safely stopped"));

    controller.reset();
    QVERIFY(!controller.routeEnded());
    QTest::qWait(500);
    QVERIFY2(controller.speedMps() > 0.05,
             "Reset must restart a route whose endpoint timer was quiesced.");
}

void NativeVehicleControllerTests::snowAccumulationChangesThePhysicalGripBudget()
{
    NativeVehicleController controller;
    QSignalSpy weatherChanged(&controller, &NativeVehicleController::weatherChanged);
    QCOMPARE(controller.snowAccumulation(), 0.0);
    QVERIFY(std::abs(controller.effectiveTyreFriction() - 1.05) < 1.0e-9);

    controller.setSnowAccumulation(1.0);
    QCOMPARE(controller.snowAccumulation(), 1.0);
    QVERIFY(std::abs(controller.effectiveTyreFriction() - 0.441) < 1.0e-9);
    QCOMPARE(weatherChanged.count(), 1);

    controller.setSnowAccumulation(5.0);
    QCOMPARE(controller.snowAccumulation(), 1.0);
    QCOMPARE(weatherChanged.count(), 1);
    controller.setSnowAccumulation(-1.0);
    QCOMPARE(controller.snowAccumulation(), 0.0);
    QCOMPARE(weatherChanged.count(), 2);
}

QTEST_GUILESS_MAIN(NativeVehicleControllerTests)
#include "NativeVehicleControllerTests.moc"
