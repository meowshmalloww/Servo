#include "MediaSourceModel.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QImage>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QTest>
#include <QUuid>

#include <memory>

class MediaSourceModelTests final : public QObject
{
    Q_OBJECT

private slots:
    void initTestCase();
    void probesImageWithoutCopyingSource();
    void probesVideoWithFfprobe();
    void scansSupportedMediaRecursively();
    void exportsReadyWorkerSources();
    void deduplicatesCanonicalPaths();
    void persistsReadyMetadata();
    void reportsMissingSourcesAfterRestart();
    void reportsCorruptMediaWithoutBlockingOtherSources();
    void countsOnlyReadyBytesForReconstruction();

private:
    static QString roleString(const MediaSourceModel &model, int row, int role);
    static bool createImage(const QString &path, const QSize &size);
    static bool createVideo(const QString &path);

    QTemporaryDir m_sources;
    std::unique_ptr<MediaSourceModel> m_model;
    QString m_primaryImagePath;
};

void MediaSourceModelTests::initTestCase()
{
    QVERIFY2(m_sources.isValid(), "Unable to create the temporary source directory");
    QStandardPaths::setTestModeEnabled(true);
    QCoreApplication::setOrganizationName(QStringLiteral("ServoTests"));
    QCoreApplication::setApplicationName(
        QStringLiteral("MediaSourceModel-%1")
            .arg(QUuid::createUuid().toString(QUuid::WithoutBraces)));
    m_model = std::make_unique<MediaSourceModel>();
}

void MediaSourceModelTests::probesImageWithoutCopyingSource()
{
    m_primaryImagePath = m_sources.filePath(QStringLiteral("source image.png"));
    QVERIFY(createImage(m_primaryImagePath, QSize(37, 23)));

    m_model->addUrl(QUrl::fromLocalFile(m_primaryImagePath));
    QTRY_VERIFY_WITH_TIMEOUT(!m_model->busy(), 10000);
    QCOMPARE(m_model->count(), 1);
    QCOMPARE(m_model->readyCount(), 1);
    QCOMPARE(roleString(*m_model, 0, MediaSourceModel::KindRole),
             QStringLiteral("image"));
    QCOMPARE(roleString(*m_model, 0, MediaSourceModel::DimensionsRole),
             QStringLiteral("37 × 23"));
    QVERIFY(roleString(*m_model, 0, MediaSourceModel::FingerprintRole)
                .startsWith(QStringLiteral("sha256-sampled-v1:")));
    QVERIFY(QFileInfo::exists(m_primaryImagePath));

    m_model->removeReference(0);
    QCOMPARE(m_model->count(), 0);
    QVERIFY2(QFileInfo::exists(m_primaryImagePath),
             "Removing a catalog reference must never delete source media");

    m_model->addUrl(QUrl::fromLocalFile(m_primaryImagePath));
    QTRY_VERIFY_WITH_TIMEOUT(!m_model->busy(), 10000);
}

void MediaSourceModelTests::probesVideoWithFfprobe()
{
    if (!m_model->ffprobeAvailable())
        QSKIP("ffprobe is not installed in the test environment");

    const QString path = m_sources.filePath(QStringLiteral("variable name video.mkv"));
    QVERIFY2(createVideo(path), "Unable to create the FFmpeg video fixture");

    m_model->addUrl(QUrl::fromLocalFile(path));
    QTRY_VERIFY_WITH_TIMEOUT(!m_model->busy(), 15000);
    QCOMPARE(m_model->count(), 2);
    QCOMPARE(m_model->readyCount(), 2);
    QCOMPARE(roleString(*m_model, 1, MediaSourceModel::KindRole),
             QStringLiteral("video"));
    QCOMPARE(roleString(*m_model, 1, MediaSourceModel::DimensionsRole),
             QStringLiteral("64 × 48"));
    const double fps = m_model->data(m_model->index(1),
                                     MediaSourceModel::FramesPerSecondRole)
                           .toDouble();
    QVERIFY(fps > 29.9 && fps < 30.1);
    const double duration = m_model->data(m_model->index(1),
                                          MediaSourceModel::DurationSecondsRole)
                                .toDouble();
    QVERIFY(duration >= 0.9 && duration <= 1.1);
}

void MediaSourceModelTests::scansSupportedMediaRecursively()
{
    const QString folder = m_sources.filePath(QStringLiteral("nested sources"));
    const QString nested = folder + QStringLiteral("/camera A");
    QVERIFY(QDir().mkpath(nested));
    QVERIFY(createImage(nested + QStringLiteral("/frame 001.png"), QSize(11, 7)));
    QVERIFY(createImage(nested + QStringLiteral("/frame 002.jpg"), QSize(13, 9)));

    m_model->addUrl(QUrl::fromLocalFile(folder));
    QTRY_VERIFY_WITH_TIMEOUT(!m_model->busy(), 15000);
    QCOMPARE(m_model->count(), 4);
    QCOMPARE(m_model->readyCount(), 4);
    QCOMPARE(m_model->errorCount(), 0);
}

void MediaSourceModelTests::exportsReadyWorkerSources()
{
    const QVariantList sources = m_model->readySources();
    QCOMPARE(sources.size(), m_model->readyCount());
    QVERIFY(!sources.isEmpty());
    for (const QVariant &value : sources) {
        const QVariantMap source = value.toMap();
        QVERIFY(QFileInfo::exists(source.value(QStringLiteral("path")).toString()));
        QVERIFY(source.value(QStringLiteral("kind")).toString()
                    == QStringLiteral("image")
                || source.value(QStringLiteral("kind")).toString()
                       == QStringLiteral("video"));
        QVERIFY(source.value(QStringLiteral("sizeBytes")).toString().toULongLong() > 0);
        QVERIFY(!source.value(QStringLiteral("catalogFingerprint")).toString().isEmpty());
    }
}

void MediaSourceModelTests::deduplicatesCanonicalPaths()
{
    const int originalCount = m_model->count();
    const QString aliasedPath = QFileInfo(m_primaryImagePath)
                                    .dir()
                                    .filePath(QStringLiteral("nested/../source image.png"));
    m_model->addUrl(QUrl::fromLocalFile(aliasedPath));
    QTRY_VERIFY_WITH_TIMEOUT(!m_model->busy(), 10000);
    QCOMPARE(m_model->count(), originalCount);
}

void MediaSourceModelTests::persistsReadyMetadata()
{
    const int expectedCount = m_model->count();
    const QString catalogPath = m_model->catalogPath();
    m_model.reset();

    QVERIFY2(QFileInfo::exists(catalogPath),
             "The catalog must be committed when the model shuts down");

    QFile catalog(catalogPath);
    QVERIFY(catalog.open(QIODevice::ReadOnly));
    const QJsonDocument document = QJsonDocument::fromJson(catalog.readAll());
    QVERIFY(document.isObject());
    QCOMPARE(document.object().value(QStringLiteral("schema")).toString(),
             QStringLiteral("servo.media-sources/v1"));

    m_model = std::make_unique<MediaSourceModel>();
    QTRY_VERIFY_WITH_TIMEOUT(!m_model->busy(), 10000);
    QCOMPARE(m_model->count(), expectedCount);
    QCOMPARE(m_model->readyCount(), expectedCount);
    QCOMPARE(m_model->errorCount(), 0);
}

void MediaSourceModelTests::reportsMissingSourcesAfterRestart()
{
    const int expectedCount = m_model->count();
    QVERIFY(QFile::remove(m_primaryImagePath));
    m_model.reset();

    m_model = std::make_unique<MediaSourceModel>();
    QTRY_VERIFY_WITH_TIMEOUT(!m_model->busy(), 10000);
    QCOMPARE(m_model->count(), expectedCount);
    QCOMPARE(m_model->readyCount(), expectedCount - 1);
    QCOMPARE(m_model->errorCount(), 1);
}

void MediaSourceModelTests::reportsCorruptMediaWithoutBlockingOtherSources()
{
    const int originalReadyCount = m_model->readyCount();
    const int originalErrorCount = m_model->errorCount();
    const QString path = m_sources.filePath(QStringLiteral("corrupt source.mp4"));
    QFile file(path);
    QVERIFY(file.open(QIODevice::WriteOnly));
    QCOMPARE(file.write("this is not a video"), qint64(19));
    file.close();

    m_model->addUrl(QUrl::fromLocalFile(path));
    QTRY_VERIFY_WITH_TIMEOUT(!m_model->busy(), 10000);
    QCOMPARE(m_model->readyCount(), originalReadyCount);
    QCOMPARE(m_model->errorCount(), originalErrorCount + 1);
    QCOMPARE(roleString(*m_model, m_model->count() - 1, MediaSourceModel::StatusRole),
             QStringLiteral("error"));
    QVERIFY(!roleString(*m_model,
                        m_model->count() - 1,
                        MediaSourceModel::ErrorTextRole)
                 .isEmpty());
}

void MediaSourceModelTests::countsOnlyReadyBytesForReconstruction()
{
    quint64 expectedReadyBytes = 0;
    const QVariantList sources = m_model->readySources();
    for (const QVariant &value : sources)
        expectedReadyBytes += value.toMap().value(QStringLiteral("sizeBytes")).toULongLong();

    QCOMPARE(m_model->readyBytes(), expectedReadyBytes);
    QVERIFY(m_model->readyBytes() < m_model->totalBytes());
}

QString MediaSourceModelTests::roleString(const MediaSourceModel &model,
                                          int row,
                                          int role)
{
    return model.data(model.index(row), role).toString();
}

bool MediaSourceModelTests::createImage(const QString &path, const QSize &size)
{
    QImage image(size, QImage::Format_RGBA8888);
    image.fill(QColor(QStringLiteral("#375b75")));
    return image.save(path);
}

bool MediaSourceModelTests::createVideo(const QString &path)
{
    const QString ffmpeg = QStandardPaths::findExecutable(QStringLiteral("ffmpeg"));
    if (ffmpeg.isEmpty())
        return false;

    QProcess process;
    process.start(ffmpeg,
                  { QStringLiteral("-hide_banner"),
                    QStringLiteral("-loglevel"),
                    QStringLiteral("error"),
                    QStringLiteral("-f"),
                    QStringLiteral("lavfi"),
                    QStringLiteral("-i"),
                    QStringLiteral("testsrc=size=64x48:rate=30000/1001"),
                    QStringLiteral("-t"),
                    QStringLiteral("1"),
                    QStringLiteral("-c:v"),
                    QStringLiteral("ffv1"),
                    QStringLiteral("-y"),
                    path });
    return process.waitForStarted(5000) && process.waitForFinished(15000)
           && process.exitStatus() == QProcess::NormalExit
           && process.exitCode() == 0 && QFileInfo(path).size() > 0;
}

QTEST_GUILESS_MAIN(MediaSourceModelTests)

#include "MediaSourceModelTests.moc"
