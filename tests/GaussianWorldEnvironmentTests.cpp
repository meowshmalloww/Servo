#include "GaussianSplatView.h"

#include <QDir>
#include <QCryptographicHash>
#include <QFile>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QTest>

#include <cmath>

namespace {

bool writeManifest(const QString &directory, const QByteArray &contents)
{
    QFile file(QDir(directory).filePath(QStringLiteral("world.json")));
    return file.open(QIODevice::WriteOnly | QIODevice::Truncate) == true
           && file.write(contents) == contents.size();
}

QByteArray manifestBytes(const QString &pipelineRevision,
                         const QJsonValue &environment = QJsonValue(QJsonValue::Undefined))
{
    QJsonObject manifest {
        { QStringLiteral("schema"), QStringLiteral("servo.gaussian-world/v1") },
        { QStringLiteral("pipelineRevision"), pipelineRevision },
    };
    if (!environment.isUndefined())
        manifest.insert(QStringLiteral("environment"), environment);
    return QJsonDocument(manifest).toJson(QJsonDocument::Compact);
}

QString sha256File(const QString &path)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        return {};
    QCryptographicHash digest(QCryptographicHash::Sha256);
    while (!file.atEnd())
        digest.addData(file.read(1024 * 1024));
    return QStringLiteral("sha256:") + QString::fromLatin1(digest.result().toHex());
}

QJsonObject observedDirectionalDescriptor(const QString &assetHash)
{
    return {
        { QStringLiteral("schema"),
          QStringLiteral("servo.observed-directional-environment/v1") },
        { QStringLiteral("method"),
          QStringLiteral("oneformer-observed-sky-equirectangular-rgba-v1") },
        { QStringLiteral("projection"),
          QStringLiteral("equirectangular-atan2-x-z-y-up-v1") },
        { QStringLiteral("asset"),
          QStringLiteral("environment/observed-sky-equirectangular.png") },
        { QStringLiteral("assetSha256"), assetHash },
        { QStringLiteral("width"), 64 },
        { QStringLiteral("height"), 32 },
        { QStringLiteral("colorSpace"), QStringLiteral("srgb") },
        { QStringLiteral("sourceSkyLabel"), 17 },
        { QStringLiteral("containsGeneratedPixels"), false },
        { QStringLiteral("finiteGeometry"), false },
        { QStringLiteral("metric"), false },
    };
}

} // namespace

class GaussianWorldEnvironmentTests final : public QObject
{
    Q_OBJECT

private slots:
    void standalonePlyUsesBlackFallback();
    void legacyR6UsesBlackFallback();
    void r7ReadsExactSrgbBackground();
    void r7ReadsObservedDirectionalSkyEvidence();
    void observedDirectionalSkyRejectsInventedUnknownTexel();
    void legacyWorldWithoutEnvironmentUsesBlackFallback();
    void malformedManifestFailsClosed();
    void malformedBackgroundFailsClosed_data();
    void malformedBackgroundFailsClosed();
    void diagnosticsAlwaysClearToBlack();
};

void GaussianWorldEnvironmentTests::standalonePlyUsesBlackFallback()
{
    QTemporaryDir directory;
    QVERIFY(directory.isValid());
    QVector3D background(1.0f, 1.0f, 1.0f);
    QString error;

    QVERIFY(Servo::Rendering::readGaussianWorldBackground(
        QDir(directory.path()).filePath(QStringLiteral("world.ply")),
        &background,
        &error));
    QCOMPARE(background, QVector3D(0.0f, 0.0f, 0.0f));
    QVERIFY(error.isEmpty());
}

void GaussianWorldEnvironmentTests::legacyR6UsesBlackFallback()
{
    QTemporaryDir directory;
    QVERIFY(directory.isValid());
    const QJsonObject configuration {
        { QStringLiteral("pipelineRevision"),
          QStringLiteral("native-colmap-servo-fidelity-gs-r6") },
    };
    const QJsonObject manifest {
        { QStringLiteral("schema"), QStringLiteral("servo.gaussian-world/v1") },
        { QStringLiteral("training"),
          QJsonObject { { QStringLiteral("configuration"), configuration } } },
    };
    QVERIFY(writeManifest(directory.path(),
                          QJsonDocument(manifest).toJson(QJsonDocument::Compact)));

    QVector3D background(1.0f, 1.0f, 1.0f);
    QString error;
    QVERIFY(Servo::Rendering::readGaussianWorldBackground(
        QDir(directory.path()).filePath(QStringLiteral("world.ply")),
        &background,
        &error));
    QCOMPARE(background, QVector3D(0.0f, 0.0f, 0.0f));
    QVERIFY(error.isEmpty());
}

void GaussianWorldEnvironmentTests::r7ReadsExactSrgbBackground()
{
    QTemporaryDir directory;
    QVERIFY(directory.isValid());
    const QJsonObject environment {
        { QStringLiteral("backgroundColorSrgb"), QJsonArray { 0.125, 0.5, 1.0 } },
    };
    QVERIFY(writeManifest(
        directory.path(),
        manifestBytes(QStringLiteral("native-colmap-servo-road-geometry-r7"), environment)));

    QVector3D background;
    QString error;
    QVERIFY2(Servo::Rendering::readGaussianWorldBackground(
                 QDir(directory.path()).filePath(QStringLiteral("world.ply")),
                 &background,
                 &error),
             qPrintable(error));
    QCOMPARE(background, QVector3D(0.125f, 0.5f, 1.0f));

    const QColor appearance = Servo::Rendering::gaussianAccumulationClearColor(background, 0);
    QCOMPARE(appearance, QColor::fromRgbF(0.0f, 0.0f, 0.0f, 0.0f));
}

void GaussianWorldEnvironmentTests::r7ReadsObservedDirectionalSkyEvidence()
{
    QTemporaryDir directory;
    QVERIFY(directory.isValid());
    QVERIFY(QDir(directory.path()).mkpath(QStringLiteral("environment")));
    const QString asset = QDir(directory.path()).filePath(
        QStringLiteral("environment/observed-sky-equirectangular.png"));
    QImage image(64, 32, QImage::Format_RGBA8888);
    image.fill(Qt::transparent);
    image.setPixelColor(5, 7, QColor::fromRgbF(0.25f, 0.5f, 0.75f, 1.0f));
    QVERIFY(image.save(asset));

    QJsonObject environment {
        { QStringLiteral("backgroundColorSrgb"), QJsonArray { 0.1, 0.2, 0.3 } },
        { QStringLiteral("backgroundSource"),
          QStringLiteral("observed-oneformer-sky-equirectangular-plus-mean-fallback-srgb-v1") },
        { QStringLiteral("observedDirectionalEnvironment"),
          observedDirectionalDescriptor(sha256File(asset)) },
    };
    QVERIFY(writeManifest(
        directory.path(),
        manifestBytes(QStringLiteral("native-colmap-servo-road-geometry-r7"), environment)));

    Servo::Rendering::GaussianWorldEnvironment parsed;
    QString error;
    QVERIFY2(Servo::Rendering::readGaussianWorldEnvironment(
                 QDir(directory.path()).filePath(QStringLiteral("world.ply")),
                 &parsed,
                 &error),
             qPrintable(error));
    QVERIFY(parsed.hasObservedDirectionalEnvironment);
    QCOMPARE(parsed.backgroundColorSrgb, QVector3D(0.1f, 0.2f, 0.3f));
    QCOMPARE(parsed.observedDirectionalRgba.size(), QSize(64, 32));
    const QColor observed = parsed.observedDirectionalRgba.pixelColor(5, 7);
    QCOMPARE(observed.red(), 64);
    QCOMPARE(observed.green(), 128);
    QCOMPARE(observed.blue(), 191);
    QCOMPARE(observed.alpha(), 255);
}

void GaussianWorldEnvironmentTests::observedDirectionalSkyRejectsInventedUnknownTexel()
{
    QTemporaryDir directory;
    QVERIFY(directory.isValid());
    QVERIFY(QDir(directory.path()).mkpath(QStringLiteral("environment")));
    const QString asset = QDir(directory.path()).filePath(
        QStringLiteral("environment/observed-sky-equirectangular.png"));
    QImage image(64, 32, QImage::Format_RGBA8888);
    image.fill(QColor(12, 34, 56, 0)); // Unknown texels must not store fabricated RGB.
    QVERIFY(image.save(asset));
    const QJsonObject environment {
        { QStringLiteral("backgroundColorSrgb"), QJsonArray { 0.1, 0.2, 0.3 } },
        { QStringLiteral("backgroundSource"),
          QStringLiteral("observed-oneformer-sky-equirectangular-plus-mean-fallback-srgb-v1") },
        { QStringLiteral("observedDirectionalEnvironment"),
          observedDirectionalDescriptor(sha256File(asset)) },
    };
    QVERIFY(writeManifest(
        directory.path(),
        manifestBytes(QStringLiteral("native-colmap-servo-road-geometry-r7"), environment)));

    Servo::Rendering::GaussianWorldEnvironment parsed;
    QString error;
    QVERIFY(!Servo::Rendering::readGaussianWorldEnvironment(
        QDir(directory.path()).filePath(QStringLiteral("world.ply")), &parsed, &error));
    QVERIFY(error.contains(QStringLiteral("zero RGB")));
}

void GaussianWorldEnvironmentTests::legacyWorldWithoutEnvironmentUsesBlackFallback()
{
    QTemporaryDir directory;
    QVERIFY(directory.isValid());
    QVERIFY(writeManifest(
        directory.path(),
        manifestBytes(QStringLiteral("native-colmap-servo-road-geometry-r7"))));

    QVector3D background(1.0f, 1.0f, 1.0f);
    QString error;
    QVERIFY(Servo::Rendering::readGaussianWorldBackground(
        QDir(directory.path()).filePath(QStringLiteral("world.ply")),
        &background,
        &error));
    QCOMPARE(background, QVector3D(0.0f, 0.0f, 0.0f));
    QVERIFY(error.isEmpty());
}

void GaussianWorldEnvironmentTests::malformedManifestFailsClosed()
{
    QTemporaryDir directory;
    QVERIFY(directory.isValid());
    QVERIFY(writeManifest(directory.path(), QByteArrayLiteral("{ not-json")));

    QVector3D background;
    QString error;
    QVERIFY(!Servo::Rendering::readGaussianWorldBackground(
        QDir(directory.path()).filePath(QStringLiteral("world.ply")),
        &background,
        &error));
    QVERIFY(error.contains(QStringLiteral("malformed")));
}

void GaussianWorldEnvironmentTests::malformedBackgroundFailsClosed_data()
{
    QTest::addColumn<QJsonValue>("background");
    QTest::newRow("not-an-array") << QJsonValue(QStringLiteral("black"));
    QTest::newRow("too-short") << QJsonValue(QJsonArray { 0.0, 0.0 });
    QTest::newRow("too-long") << QJsonValue(QJsonArray { 0.0, 0.0, 0.0, 0.0 });
    QTest::newRow("string-component")
        << QJsonValue(QJsonArray { 0.0, QStringLiteral("0.5"), 1.0 });
    QTest::newRow("negative") << QJsonValue(QJsonArray { -0.01, 0.5, 1.0 });
    QTest::newRow("above-one") << QJsonValue(QJsonArray { 0.0, 0.5, 1.01 });
}

void GaussianWorldEnvironmentTests::malformedBackgroundFailsClosed()
{
    QFETCH(QJsonValue, background);
    QTemporaryDir directory;
    QVERIFY(directory.isValid());
    const QJsonObject environment {
        { QStringLiteral("backgroundColorSrgb"), background },
    };
    QVERIFY(writeManifest(
        directory.path(),
        manifestBytes(QStringLiteral("native-colmap-servo-road-geometry-r7"), environment)));

    QVector3D parsedBackground;
    QString error;
    QVERIFY(!Servo::Rendering::readGaussianWorldBackground(
        QDir(directory.path()).filePath(QStringLiteral("world.ply")),
        &parsedBackground,
        &error));
    QVERIFY(!error.isEmpty());
}

void GaussianWorldEnvironmentTests::diagnosticsAlwaysClearToBlack()
{
    const QVector3D background(0.2f, 0.4f, 0.8f);
    for (int visualizationMode = 1; visualizationMode <= 3; ++visualizationMode) {
        const QColor clear = Servo::Rendering::gaussianAccumulationClearColor(
            background,
            visualizationMode);
        QCOMPARE(clear, QColor::fromRgbF(0.0f, 0.0f, 0.0f, 1.0f));
    }
}

QTEST_GUILESS_MAIN(GaussianWorldEnvironmentTests)
#include "GaussianWorldEnvironmentTests.moc"
