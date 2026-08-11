#include "ReconstructionController.h"

#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QTest>

class ReconstructionControllerTests final : public QObject
{
    Q_OBJECT

private slots:
    void acceptsAlgorithmQualifiedHashes();
    void acceptsLegacyBareHashes();
    void rejectsArtifactHashMismatch();
    void rejectsHashPathOutsideBundle();

private:
    struct BundleFixture {
        QString jobPath;
        QString worldPath;
    };

    static BundleFixture createBundle(const QTemporaryDir &temporary,
                                      bool algorithmQualified);
    static bool writeFile(const QString &path, const QByteArray &contents);
    static QString sha256(const QByteArray &contents);
    static QJsonObject readManifest(const QString &worldPath);
    static bool writeManifest(const QString &worldPath, const QJsonObject &manifest);
};

namespace {
constexpr auto worldId = "world-test-id";
constexpr auto pipelineRevision = "native-colmap-servo-fidelity-gs-r6";
}

void ReconstructionControllerTests::acceptsAlgorithmQualifiedHashes()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    const BundleFixture fixture = createBundle(temporary, true);

    QString error;
    QVERIFY2(ReconstructionController::validatePublishedWorld(fixture.worldPath,
                                                               fixture.jobPath,
                                                               QString::fromLatin1(worldId),
                                                               QString::fromLatin1(pipelineRevision),
                                                               &error),
             qPrintable(error));
}

void ReconstructionControllerTests::acceptsLegacyBareHashes()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    const BundleFixture fixture = createBundle(temporary, false);

    QString error;
    QVERIFY2(ReconstructionController::validatePublishedWorld(fixture.worldPath,
                                                               fixture.jobPath,
                                                               QString::fromLatin1(worldId),
                                                               QString::fromLatin1(pipelineRevision),
                                                               &error),
             qPrintable(error));
}

void ReconstructionControllerTests::rejectsArtifactHashMismatch()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    const BundleFixture fixture = createBundle(temporary, true);
    QVERIFY(writeFile(QDir(fixture.worldPath).filePath(QStringLiteral("appearance.json")),
                      QByteArrayLiteral("tampered\n")));

    QString error;
    QVERIFY(!ReconstructionController::validatePublishedWorld(fixture.worldPath,
                                                                fixture.jobPath,
                                                                QString::fromLatin1(worldId),
                                                                QString::fromLatin1(pipelineRevision),
                                                                &error));
    QCOMPARE(error, QStringLiteral("Artifact hash mismatch: appearance.json"));
}

void ReconstructionControllerTests::rejectsHashPathOutsideBundle()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    const BundleFixture fixture = createBundle(temporary, true);
    const QByteArray outsideContents = QByteArrayLiteral("outside\n");
    const QString outsidePath = QDir(fixture.worldPath)
                                    .filePath(QStringLiteral("../outside.bin"));
    QVERIFY(writeFile(outsidePath, outsideContents));

    QJsonObject manifest = readManifest(fixture.worldPath);
    QVERIFY(!manifest.isEmpty());
    QJsonObject hashes = manifest.value(QStringLiteral("hashes")).toObject();
    hashes.insert(QStringLiteral("../outside.bin"),
                  QStringLiteral("sha256:") + sha256(outsideContents));
    manifest.insert(QStringLiteral("hashes"), hashes);
    QVERIFY(writeManifest(fixture.worldPath, manifest));

    QString error;
    QVERIFY(!ReconstructionController::validatePublishedWorld(fixture.worldPath,
                                                                fixture.jobPath,
                                                                QString::fromLatin1(worldId),
                                                                QString::fromLatin1(pipelineRevision),
                                                                &error));
    QCOMPARE(error,
             QStringLiteral("Hash entry '../outside.bin' is malformed or points outside the bundle."));
}

ReconstructionControllerTests::BundleFixture
ReconstructionControllerTests::createBundle(const QTemporaryDir &temporary,
                                             bool algorithmQualified)
{
    const QString jobRoot = QDir(temporary.path()).filePath(QStringLiteral("job"));
    const QString worldPath = QDir(jobRoot)
                                  .filePath(QStringLiteral("stages/publish/world"));
    if (!QDir().mkpath(worldPath))
        return {};

    const QString jobPath = QDir(jobRoot).filePath(QStringLiteral("job.json"));
    if (!writeFile(jobPath, QByteArrayLiteral("{}\n")))
        return {};

    const QByteArray plyContents = QByteArrayLiteral(
        "ply\nformat ascii 1.0\nelement vertex 0\nend_header\n");
    const QByteArray appearanceContents = QByteArrayLiteral("{\"schema\":\"test\"}\n");
    if (!writeFile(QDir(worldPath).filePath(QStringLiteral("world.ply")), plyContents)
        || !writeFile(QDir(worldPath).filePath(QStringLiteral("appearance.json")),
                      appearanceContents)) {
        return {};
    }

    const QString prefix = algorithmQualified ? QStringLiteral("sha256:") : QString();
    const QJsonObject artifacts {
        { QStringLiteral("ply"), QStringLiteral("world.ply") },
        { QStringLiteral("appearance"), QStringLiteral("appearance.json") },
    };
    const QJsonObject hashes {
        { QStringLiteral("world.ply"), prefix + sha256(plyContents) },
        { QStringLiteral("appearance.json"), prefix + sha256(appearanceContents) },
    };
    const QJsonObject manifest {
        { QStringLiteral("schema"), QStringLiteral("servo.gaussian-world/v1") },
        { QStringLiteral("worldId"), QString::fromLatin1(worldId) },
        { QStringLiteral("pipelineRevision"), QString::fromLatin1(pipelineRevision) },
        { QStringLiteral("artifacts"), artifacts },
        { QStringLiteral("hashes"), hashes },
    };
    if (!writeManifest(worldPath, manifest))
        return {};
    return { jobPath, worldPath };
}

bool ReconstructionControllerTests::writeFile(const QString &path,
                                               const QByteArray &contents)
{
    QFile file(path);
    return file.open(QIODevice::WriteOnly | QIODevice::Truncate)
           && file.write(contents) == contents.size();
}

QString ReconstructionControllerTests::sha256(const QByteArray &contents)
{
    return QString::fromLatin1(
        QCryptographicHash::hash(contents, QCryptographicHash::Sha256).toHex());
}

QJsonObject ReconstructionControllerTests::readManifest(const QString &worldPath)
{
    QFile file(QDir(worldPath).filePath(QStringLiteral("world.json")));
    if (!file.open(QIODevice::ReadOnly))
        return {};
    return QJsonDocument::fromJson(file.readAll()).object();
}

bool ReconstructionControllerTests::writeManifest(const QString &worldPath,
                                                   const QJsonObject &manifest)
{
    return writeFile(QDir(worldPath).filePath(QStringLiteral("world.json")),
                     QJsonDocument(manifest).toJson(QJsonDocument::Compact));
}

QTEST_GUILESS_MAIN(ReconstructionControllerTests)

#include "ReconstructionControllerTests.moc"
