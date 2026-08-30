#include "WorldLibraryModel.h"

#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>

class WorldLibraryModelTests final : public QObject
{
    Q_OBJECT

private slots:
    void discoversVerifiedPublishedJobs();
    void surfacesTerminalFailedJobsForDiagnosis();
    void readsR6PreferredQualityShape();
    void rejectsArtifactOutsideWorldBundle();
    void filtersSortsAndPersistsAliases();
    void migratesOnceToBestQualifiedVisualRoute();
    void deletesOnlyKnownJobDirectory();

private:
    static QString createWorld(const QString &jobsRoot,
                               const QString &worldId,
                               const QString &name,
                               const QString &createdAt,
                               const QString &plyRelativePath = QStringLiteral("world.ply"));
    static QString createFailedJob(const QString &jobsRoot,
                                   const QString &jobId,
                                   const QString &name,
                                   const QString &createdAt);
    static bool writeFile(const QString &path, const QByteArray &contents);
};

void WorldLibraryModelTests::discoversVerifiedPublishedJobs()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    const QString jobsRoot = QDir(temporary.path()).filePath(QStringLiteral("jobs"));
    const QString catalogPath = QDir(temporary.path()).filePath(QStringLiteral("library.json"));
    const QString worldId = QStringLiteral("11111111-1111-1111-1111-111111111111");
    const QString worldPath = createWorld(jobsRoot,
                                          worldId,
                                          QStringLiteral("Courtyard"),
                                          QStringLiteral("2026-08-10T20:26:36.036Z"));
    QVERIFY(!worldPath.isEmpty());
    QVERIFY(QDir().mkpath(QDir(jobsRoot).filePath(QStringLiteral("incomplete-job"))));

    WorldLibraryModel model(jobsRoot, catalogPath);
    QTRY_VERIFY_WITH_TIMEOUT(!model.busy(), 10000);
    QCOMPARE(model.totalCount(), 1);
    QCOMPARE(model.count(), 1);
    QCOMPARE(model.selectedWorldId(), worldId);
    QVERIFY(model.hasSelection());

    const QModelIndex item = model.index(0, 0);
    QCOMPARE(model.data(item, WorldLibraryModel::DisplayNameRole).toString(),
             QStringLiteral("Courtyard"));
    QCOMPARE(model.data(item, WorldLibraryModel::GaussianCountRole).toLongLong(),
             1188206);
    QCOMPARE(model.data(item, WorldLibraryModel::QualityTierRole).toString(),
             QStringLiteral("degraded-experimental"));
    QCOMPARE(model.data(item, WorldLibraryModel::WorldPathRole).toString(),
             QFileInfo(worldPath).canonicalFilePath());
    QVERIFY(model.totalBytes() > 0);
    QVERIFY(!model.selectedWorld().value(QStringLiteral("previewUrl")).toUrl().isEmpty());
    QVERIFY(model.selectedWorld().value(QStringLiteral("plyUrl")).toUrl().isLocalFile());
    QCOMPARE(model.data(item, WorldLibraryModel::RecordedFrameCountRole).toInt(), 2);
    const QVariantList recordedFrames = model.data(
        item, WorldLibraryModel::RecordedFrameUrlsRole).toList();
    QCOMPARE(recordedFrames.size(), 2);
    QVERIFY(recordedFrames.first().toUrl().isLocalFile());
}

void WorldLibraryModelTests::surfacesTerminalFailedJobsForDiagnosis()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    const QString jobsRoot = QDir(temporary.path()).filePath(QStringLiteral("jobs"));
    const QString catalogPath = QDir(temporary.path()).filePath(QStringLiteral("library.json"));
    const QString jobId = QStringLiteral("77777777-7777-7777-7777-777777777777");
    QVERIFY(!createFailedJob(jobsRoot,
                             jobId,
                             QStringLiteral("Yosemite road"),
                             QStringLiteral("2026-08-14T10:30:00.000Z"))
                 .isEmpty());

    WorldLibraryModel model(jobsRoot, catalogPath);
    QTRY_VERIFY_WITH_TIMEOUT(!model.busy(), 10000);
    QCOMPARE(model.totalCount(), 1);
    QCOMPARE(model.selectedWorldId(), jobId);

    const QModelIndex item = model.index(0, 0);
    QCOMPARE(model.data(item, WorldLibraryModel::QualityTierRole).toString(),
             QStringLiteral("failed"));
    QVERIFY(!model.data(item, WorldLibraryModel::PublishedRole).toBool());
    QVERIFY(model.data(item, WorldLibraryModel::PlyPathRole).toString().isEmpty());
    QVERIFY(!model.data(item, WorldLibraryModel::PreviewUrlRole).toUrl().isEmpty());
    QVERIFY(model.data(item, WorldLibraryModel::FailureTextRole)
                .toString()
                .contains(QStringLiteral("no publishable Gaussian world")));
}

void WorldLibraryModelTests::readsR6PreferredQualityShape()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    const QString jobsRoot = QDir(temporary.path()).filePath(QStringLiteral("jobs"));
    const QString catalogPath = QDir(temporary.path()).filePath(QStringLiteral("library.json"));
    const QString worldId = QStringLiteral("66666666-6666-6666-6666-666666666666");
    const QString worldPath = createWorld(jobsRoot,
                                          worldId,
                                          QStringLiteral("Preferred road"),
                                          QStringLiteral("2026-08-11T17:04:46.751Z"));
    QVERIFY(!worldPath.isEmpty());

    const QString manifestPath = QDir(worldPath).filePath(QStringLiteral("world.json"));
    QFile manifestFile(manifestPath);
    QVERIFY(manifestFile.open(QIODevice::ReadOnly));
    QJsonObject manifest = QJsonDocument::fromJson(manifestFile.readAll()).object();
    manifestFile.close();
    manifest.insert(
        QStringLiteral("quality"),
        QJsonObject {
            { QStringLiteral("tier"), QStringLiteral("preferred") },
            { QStringLiteral("finalArtifact"),
              QJsonObject {
                  { QStringLiteral("psnrMean"), 24.5658 },
                  { QStringLiteral("ssimMean"), 0.81485 },
              } },
            { QStringLiteral("heldout"),
              QJsonObject {
                  { QStringLiteral("psnrMean"), 23.8692 },
                  { QStringLiteral("ssimMean"), 0.79106 },
              } },
            { QStringLiteral("cleanup"),
              QJsonObject { { QStringLiteral("retainedGaussians"), 1486817 } } },
        });
    QVERIFY(writeFile(manifestPath,
                      QJsonDocument(manifest).toJson(QJsonDocument::Compact)));

    WorldLibraryModel model(jobsRoot, catalogPath);
    QTRY_VERIFY_WITH_TIMEOUT(!model.busy(), 10000);
    QCOMPARE(model.totalCount(), 1);
    const QModelIndex item = model.index(0, 0);
    QCOMPARE(model.data(item, WorldLibraryModel::QualityTierRole).toString(),
             QStringLiteral("preferred"));
    QCOMPARE(model.data(item, WorldLibraryModel::QualityLabelRole).toString(),
             QStringLiteral("Preferred"));
    QCOMPARE(model.data(item, WorldLibraryModel::QualityToneRole).toString(),
             QStringLiteral("success"));
    QCOMPARE(model.data(item, WorldLibraryModel::PsnrRole).toDouble(), 24.5658);
    QCOMPARE(model.data(item, WorldLibraryModel::SsimRole).toDouble(), 0.81485);
    QCOMPARE(model.data(item, WorldLibraryModel::GaussianCountRole).toLongLong(),
             1486817);
}

void WorldLibraryModelTests::rejectsArtifactOutsideWorldBundle()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    const QString jobsRoot = QDir(temporary.path()).filePath(QStringLiteral("jobs"));
    const QString catalogPath = QDir(temporary.path()).filePath(QStringLiteral("library.json"));
    const QString worldId = QStringLiteral("22222222-2222-2222-2222-222222222222");
    const QString worldPath = createWorld(jobsRoot,
                                          worldId,
                                          QStringLiteral("Unsafe"),
                                          QStringLiteral("2026-08-10T20:26:36.036Z"),
                                          QStringLiteral("../outside.ply"));
    QVERIFY(!worldPath.isEmpty());
    QVERIFY(writeFile(QDir(QFileInfo(worldPath).absolutePath())
                          .filePath(QStringLiteral("outside.ply")),
                      QByteArrayLiteral("not inside the bundle")));

    WorldLibraryModel model(jobsRoot, catalogPath);
    QTRY_VERIFY_WITH_TIMEOUT(!model.busy(), 10000);
    QCOMPARE(model.totalCount(), 0);
    QVERIFY(!model.hasSelection());
}

void WorldLibraryModelTests::filtersSortsAndPersistsAliases()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    const QString jobsRoot = QDir(temporary.path()).filePath(QStringLiteral("jobs"));
    const QString catalogPath = QDir(temporary.path()).filePath(QStringLiteral("library.json"));
    const QString alphaId = QStringLiteral("33333333-3333-3333-3333-333333333333");
    const QString betaId = QStringLiteral("44444444-4444-4444-4444-444444444444");
    QVERIFY(!createWorld(jobsRoot,
                         alphaId,
                         QStringLiteral("Alpha"),
                         QStringLiteral("2026-08-09T20:00:00.000Z"))
                 .isEmpty());
    QVERIFY(!createWorld(jobsRoot,
                         betaId,
                         QStringLiteral("Beta"),
                         QStringLiteral("2026-08-10T20:00:00.000Z"))
                 .isEmpty());

    {
        WorldLibraryModel model(jobsRoot, catalogPath);
        QTRY_VERIFY_WITH_TIMEOUT(!model.busy(), 10000);
        QCOMPARE(model.totalCount(), 2);
        QCOMPARE(model.data(model.index(0, 0), WorldLibraryModel::WorldIdRole).toString(),
                 betaId);

        model.setFilterText(QStringLiteral("alpha"));
        QCOMPARE(model.count(), 1);
        QCOMPARE(model.data(model.index(0, 0), WorldLibraryModel::WorldIdRole).toString(),
                 alphaId);
        model.setFilterText({});
        model.setSortMode(QStringLiteral("name"));
        QCOMPARE(model.data(model.index(0, 0), WorldLibraryModel::WorldIdRole).toString(),
                 alphaId);
        QVERIFY(model.selectWorld(alphaId));
        QVERIFY(model.renameWorld(alphaId, QStringLiteral("Zebra Courtyard")));
        QCOMPARE(model.selectedWorld().value(QStringLiteral("displayName")).toString(),
                 QStringLiteral("Zebra Courtyard"));
    }

    WorldLibraryModel restored(jobsRoot, catalogPath);
    QTRY_VERIFY_WITH_TIMEOUT(!restored.busy(), 10000);
    QVERIFY(restored.selectWorld(alphaId));
    QCOMPARE(restored.selectedWorld().value(QStringLiteral("displayName")).toString(),
             QStringLiteral("Zebra Courtyard"));
}

void WorldLibraryModelTests::migratesOnceToBestQualifiedVisualRoute()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    const QString jobsRoot = QDir(temporary.path()).filePath(QStringLiteral("jobs"));
    const QString catalogPath = QDir(temporary.path()).filePath(QStringLiteral("library.json"));
    const QString oldId = QStringLiteral("old-selected-world");
    const QString t5Id = QStringLiteral("yosemite-t5-hybrid-full-route-v1-20260828");
    QVERIFY(!createWorld(jobsRoot,
                         oldId,
                         QStringLiteral("Old world"),
                         QStringLiteral("2026-08-28T18:00:00.000Z"))
                 .isEmpty());
    const QString t5WorldPath = createWorld(jobsRoot,
                                            t5Id,
                                            QStringLiteral("Yosemite T5 - Hybrid Full Route (Accepted)"),
                                            QStringLiteral("2026-08-28T17:00:00.000Z"));
    QVERIFY(!t5WorldPath.isEmpty());

    const QString manifestPath = QDir(t5WorldPath).filePath(QStringLiteral("world.json"));
    QFile manifestFile(manifestPath);
    QVERIFY(manifestFile.open(QIODevice::ReadOnly));
    QJsonObject manifest = QJsonDocument::fromJson(manifestFile.readAll()).object();
    manifestFile.close();
    QJsonObject quality = manifest.value(QStringLiteral("quality")).toObject();
    quality.insert(QStringLiteral("tier"), QStringLiteral("hackathon-visual-route"));
    manifest.insert(QStringLiteral("quality"), quality);
    QJsonArray routeTiles;
    for (int index = 0; index < 5; ++index) {
        const QString relativePath = QStringLiteral("tiles/tile-%1.ply").arg(index);
        QVERIFY(writeFile(QDir(t5WorldPath).filePath(relativePath), QByteArrayLiteral("ply\n")));
        routeTiles.append(QJsonObject {
            { QStringLiteral("tileId"), QStringLiteral("tile-%1").arg(index) },
            { QStringLiteral("ply"), relativePath },
            { QStringLiteral("cameraStart"), index * 10 },
            { QStringLiteral("cameraEndExclusive"), (index + 1) * 10 },
            { QStringLiteral("cameraCount"), 10 },
            { QStringLiteral("gaussianCount"), 1000 },
        });
    }
    manifest.insert(QStringLiteral("routeTiles"), routeTiles);
    QVERIFY(writeFile(manifestPath,
                      QJsonDocument(manifest).toJson(QJsonDocument::Compact)));

    const QJsonObject legacyCatalog {
        { QStringLiteral("schema"), QStringLiteral("servo.world-library/v1") },
        { QStringLiteral("selectedWorldId"), oldId },
        { QStringLiteral("selectionPolicyVersion"), 5 },
        { QStringLiteral("aliases"), QJsonObject {} },
    };
    QVERIFY(writeFile(catalogPath,
                      QJsonDocument(legacyCatalog).toJson(QJsonDocument::Compact)));

    {
        WorldLibraryModel model(jobsRoot, catalogPath);
        QTRY_VERIFY_WITH_TIMEOUT(!model.busy(), 10000);
        QCOMPARE(model.selectedWorldId(), t5Id);
        QVERIFY(model.selectWorld(oldId));
    }

    WorldLibraryModel restored(jobsRoot, catalogPath);
    QTRY_VERIFY_WITH_TIMEOUT(!restored.busy(), 10000);
    QCOMPARE(restored.selectedWorldId(), oldId);
}

void WorldLibraryModelTests::deletesOnlyKnownJobDirectory()
{
    QTemporaryDir temporary;
    QVERIFY(temporary.isValid());
    const QString jobsRoot = QDir(temporary.path()).filePath(QStringLiteral("jobs"));
    const QString catalogPath = QDir(temporary.path()).filePath(QStringLiteral("library.json"));
    const QString worldId = QStringLiteral("55555555-5555-5555-5555-555555555555");
    const QString worldPath = createWorld(jobsRoot,
                                          worldId,
                                          QStringLiteral("Delete me"),
                                          QStringLiteral("2026-08-10T20:26:36.036Z"));
    QVERIFY(!worldPath.isEmpty());
    const QString jobPath = QDir(jobsRoot).filePath(worldId);
    QVERIFY(writeFile(QDir(jobPath).filePath(QStringLiteral("checkpoint.bin")),
                      QByteArray(1024 * 1024, 'x')));

    WorldLibraryModel model(jobsRoot, catalogPath);
    QTRY_VERIFY_WITH_TIMEOUT(!model.busy(), 10000);
    QCOMPARE(model.totalCount(), 1);
    const qulonglong expectedRecovered = model.totalBytes();
    QVERIFY(expectedRecovered >= 1024 * 1024);
    QVERIFY(!model.deleteWorld(QStringLiteral("unknown-world")));
    QVERIFY(QFileInfo::exists(jobPath));
    model.clearLastError();

    QSignalSpy deletedSpy(&model, &WorldLibraryModel::worldDeleted);
    QVERIFY(model.deleteWorld(worldId));
    QTRY_COMPARE_WITH_TIMEOUT(deletedSpy.count(), 1, 10000);
    QTRY_VERIFY_WITH_TIMEOUT(!model.busy(), 10000);
    QTRY_COMPARE_WITH_TIMEOUT(model.totalCount(), 0, 10000);
    QVERIFY(!QFileInfo::exists(jobPath));
    QCOMPARE(deletedSpy.first().at(0).toString(), worldId);
    QCOMPARE(deletedSpy.first().at(2).toULongLong(), expectedRecovered);
}

QString WorldLibraryModelTests::createWorld(const QString &jobsRoot,
                                            const QString &worldId,
                                            const QString &name,
                                            const QString &createdAt,
                                            const QString &plyRelativePath)
{
    const QString jobPath = QDir(jobsRoot).filePath(worldId);
    const QString worldPath = QDir(jobPath).filePath(QStringLiteral("stages/publish/world"));
    if (!QDir().mkpath(QDir(worldPath).filePath(QStringLiteral("validation-renders"))))
        return {};

    const QJsonObject job {
        { QStringLiteral("schema"), QStringLiteral("servo.reconstruction-job/v1") },
        { QStringLiteral("jobId"), worldId },
        { QStringLiteral("worldName"), name },
        { QStringLiteral("createdAt"), createdAt },
        { QStringLiteral("profile"), QStringLiteral("balanced-12gb") },
        { QStringLiteral("sources"),
          QJsonArray { QJsonObject {
              { QStringLiteral("path"), QStringLiteral("C:/captures/walk.mov") },
              { QStringLiteral("kind"), QStringLiteral("video") },
          } } },
    };
    if (!writeFile(QDir(jobPath).filePath(QStringLiteral("job.json")),
                   QJsonDocument(job).toJson(QJsonDocument::Indented))) {
        return {};
    }

    const QJsonObject manifest {
        { QStringLiteral("schema"), QStringLiteral("servo.gaussian-world/v1") },
        { QStringLiteral("worldId"), worldId },
        { QStringLiteral("createdAt"), createdAt },
        { QStringLiteral("profile"), QStringLiteral("balanced-12gb") },
        { QStringLiteral("pipelineRevision"), QStringLiteral("test-pipeline-r1") },
        { QStringLiteral("representationType"), QStringLiteral("servo-fidelity-3dgs-v1") },
        { QStringLiteral("artifacts"),
          QJsonObject {
              { QStringLiteral("ply"), plyRelativePath },
              { QStringLiteral("validationRenders"),
                QStringLiteral("validation-renders") },
              { QStringLiteral("cameras"), QStringLiteral("cameras.json") },
          } },
        { QStringLiteral("coordinateSystem"),
          QJsonObject { { QStringLiteral("scale"),
                          QStringLiteral("unknown-monocular") } } },
        { QStringLiteral("quality"),
          QJsonObject {
              { QStringLiteral("tier"), QStringLiteral("degraded-experimental") },
              { QStringLiteral("psnrMean"), 14.75 },
              { QStringLiteral("ssimMean"), 0.410 },
              { QStringLiteral("cleanup"),
                QJsonObject { { QStringLiteral("retainedGaussians"), 1188206 } } },
          } },
    };
    if (!writeFile(QDir(worldPath).filePath(QStringLiteral("world.json")),
                   QJsonDocument(manifest).toJson(QJsonDocument::Compact))) {
        return {};
    }
    const QJsonObject cameras {
        { QStringLiteral("cameras"),
          QJsonArray {
              QJsonObject { { QStringLiteral("image"),
                              QStringLiteral("video-000/00000000.png") } },
              QJsonObject { { QStringLiteral("image"),
                              QStringLiteral("video-000/00000001.png") } },
              QJsonObject { { QStringLiteral("image"),
                              QStringLiteral("../../outside.png") } },
          } },
    };
    if (!writeFile(QDir(worldPath).filePath(QStringLiteral("cameras.json")),
                   QJsonDocument(cameras).toJson(QJsonDocument::Compact))
        || !writeFile(QDir(jobPath).filePath(
                          QStringLiteral("stages/pose/training/images/video-000/00000000.png")),
                      QByteArrayLiteral("frame zero"))
        || !writeFile(QDir(jobPath).filePath(
                          QStringLiteral("stages/pose/training/images/video-000/00000001.png")),
                      QByteArrayLiteral("frame one"))) {
        return {};
    }

    const QString plyPath = QDir(worldPath).filePath(plyRelativePath);
    if (plyRelativePath == QStringLiteral("world.ply")
        && !writeFile(plyPath, QByteArrayLiteral("ply\nformat binary_little_endian 1.0\n"))) {
        return {};
    }
    if (!writeFile(QDir(worldPath)
                       .filePath(QStringLiteral("validation-renders/compare-000.png")),
                   QByteArrayLiteral("png fixture"))) {
        return {};
    }
    return worldPath;
}

QString WorldLibraryModelTests::createFailedJob(const QString &jobsRoot,
                                                const QString &jobId,
                                                const QString &name,
                                                const QString &createdAt)
{
    const QString jobPath = QDir(jobsRoot).filePath(jobId);
    const QString validationPath = QDir(jobPath).filePath(
        QStringLiteral("stages/train/validation"));
    if (!QDir().mkpath(validationPath))
        return {};

    const QJsonObject job {
        { QStringLiteral("schema"), QStringLiteral("servo.reconstruction-job/v1") },
        { QStringLiteral("jobId"), jobId },
        { QStringLiteral("worldName"), name },
        { QStringLiteral("createdAt"), createdAt },
        { QStringLiteral("profile"), QStringLiteral("fidelity-12gb") },
        { QStringLiteral("sources"),
          QJsonArray { QJsonObject {
              { QStringLiteral("path"), QStringLiteral("C:/captures/yosemite.mov") },
              { QStringLiteral("kind"), QStringLiteral("video") },
          } } },
    };
    const QJsonObject heldout {
        { QStringLiteral("schema"), QStringLiteral("servo.gsplat-heldout-evaluation/v1") },
        { QStringLiteral("pipelineRevision"), QStringLiteral("native-colmap-servo-fidelity-gs-r7") },
        { QStringLiteral("psnrMean"), 19.59 },
        { QStringLiteral("ssimMean"), 0.746 },
    };
    if (!writeFile(QDir(jobPath).filePath(QStringLiteral("job.json")),
                   QJsonDocument(job).toJson(QJsonDocument::Compact))
        || !writeFile(QDir(jobPath).filePath(QStringLiteral("stages/train/heldout-metrics.json")),
                      QJsonDocument(heldout).toJson(QJsonDocument::Compact))
        || !writeFile(QDir(validationPath).filePath(QStringLiteral("compare-000.png")),
                      QByteArrayLiteral("png fixture"))
        || !writeFile(QDir(jobPath).filePath(QStringLiteral("events.jsonl")),
                      QByteArrayLiteral("{\"event\":\"job_failed\",\"state\":\"failed\"}\n"))) {
        return {};
    }
    return jobPath;
}

bool WorldLibraryModelTests::writeFile(const QString &path,
                                       const QByteArray &contents)
{
    if (!QDir().mkpath(QFileInfo(path).absolutePath()))
        return false;
    QFile file(path);
    return file.open(QIODevice::WriteOnly) && file.write(contents) == contents.size();
}

QTEST_GUILESS_MAIN(WorldLibraryModelTests)

#include "WorldLibraryModelTests.moc"
