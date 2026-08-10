#include "MediaSourceModel.h"

#include <QCryptographicHash>
#include <QDateTime>
#include <QDir>
#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QImageReader>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QSaveFile>
#include <QStandardPaths>
#include <QUuid>
#include <QtConcurrentRun>

#include <cmath>
#include <utility>

namespace {
constexpr qsizetype fingerprintChunkBytes = 4 * 1024 * 1024;
constexpr int probeTimeoutMilliseconds = 120000;

double jsonNumber(const QJsonValue &value, double fallback = -1.0)
{
    bool ok = false;
    const double parsed = value.isDouble() ? value.toDouble()
                                           : value.toString().toDouble(&ok);
    if (value.isDouble())
        return parsed;
    return ok && std::isfinite(parsed) ? parsed : fallback;
}

qint64 jsonInteger(const QJsonValue &value, qint64 fallback = -1)
{
    bool ok = false;
    const qint64 parsed = value.isDouble()
                              ? static_cast<qint64>(value.toDouble())
                              : value.toString().toLongLong(&ok);
    if (value.isDouble())
        return parsed;
    return ok ? parsed : fallback;
}

double rationalValue(const QString &value)
{
    const qsizetype slash = value.indexOf('/');
    if (slash < 0) {
        bool ok = false;
        const double result = value.toDouble(&ok);
        return ok && std::isfinite(result) && result > 0.0 ? result : -1.0;
    }

    bool numeratorOk = false;
    bool denominatorOk = false;
    const double numerator = value.left(slash).toDouble(&numeratorOk);
    const double denominator = value.mid(slash + 1).toDouble(&denominatorOk);
    if (!numeratorOk || !denominatorOk || denominator == 0.0)
        return -1.0;

    const double result = numerator / denominator;
    return std::isfinite(result) && result > 0.0 ? result : -1.0;
}

QString sampledFingerprint(const QString &path, quint64 sizeBytes)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        return {};

    QCryptographicHash hash(QCryptographicHash::Sha256);
    hash.addData(QByteArrayView("servo-sampled-content-v1\0", 25));
    hash.addData(QByteArray::number(sizeBytes));
    hash.addData(QByteArrayView("\0", 1));

    const QByteArray first = file.read(fingerprintChunkBytes);
    hash.addData(first);

    if (sizeBytes > static_cast<quint64>(fingerprintChunkBytes * 2)) {
        if (file.seek(static_cast<qint64>(sizeBytes) - fingerprintChunkBytes))
            hash.addData(file.read(fingerprintChunkBytes));
    } else if (!file.atEnd()) {
        hash.addData(file.readAll());
    }

    return QStringLiteral("sha256-sampled-v1:%1")
        .arg(QString::fromLatin1(hash.result().toHex()));
}

QString firstNonEmpty(const QJsonObject &object,
                      std::initializer_list<const char *> keys)
{
    for (const char *key : keys) {
        const QString value = object.value(QLatin1StringView(key)).toString();
        if (!value.isEmpty() && value != QStringLiteral("unknown"))
            return value;
    }
    return {};
}
} // namespace

struct MediaSourceModel::ProbeResult {
    bool success = false;
    QString kind = QStringLiteral("media");
    quint64 sizeBytes = 0;
    qint64 modifiedMilliseconds = 0;
    int width = 0;
    int height = 0;
    double durationSeconds = -1.0;
    double framesPerSecond = -1.0;
    qint64 frameCount = -1;
    QString codec;
    QString container;
    QString pixelFormat;
    QString colorDescription;
    int rotation = 0;
    QString fingerprint;
    QString errorText;
};

MediaSourceModel::MediaSourceModel(QObject *parent)
    : QAbstractListModel(parent)
{
    m_probePool.setMaxThreadCount(2);
    m_probePool.setExpiryTimeout(30000);
    m_scanPool.setMaxThreadCount(1);
    m_scanPool.setExpiryTimeout(30000);

    for (const QByteArray &format : QImageReader::supportedImageFormats())
        m_imageExtensions.insert(QString::fromLatin1(format).toLower());
    m_imageExtensions.unite(QSet<QString> { QStringLiteral("jpg"),
                                            QStringLiteral("jpeg"),
                                            QStringLiteral("png"),
                                            QStringLiteral("tif"),
                                            QStringLiteral("tiff"),
                                            QStringLiteral("webp"),
                                            QStringLiteral("heic"),
                                            QStringLiteral("heif"),
                                            QStringLiteral("avif"),
                                            QStringLiteral("bmp"),
                                            QStringLiteral("dng"),
                                            QStringLiteral("exr"),
                                            QStringLiteral("hdr") });

    m_folderExtensions = m_imageExtensions;
    m_folderExtensions.unite(QSet<QString> { QStringLiteral("mp4"),
                                             QStringLiteral("mov"),
                                             QStringLiteral("m4v"),
                                             QStringLiteral("mkv"),
                                             QStringLiteral("avi"),
                                             QStringLiteral("webm"),
                                             QStringLiteral("mts"),
                                             QStringLiteral("m2ts"),
                                             QStringLiteral("ts"),
                                             QStringLiteral("mxf"),
                                             QStringLiteral("mpg"),
                                             QStringLiteral("mpeg"),
                                             QStringLiteral("3gp"),
                                             QStringLiteral("3g2"),
                                             QStringLiteral("wmv"),
                                             QStringLiteral("flv"),
                                             QStringLiteral("ogv"),
                                             QStringLiteral("vob") });

    refreshFfprobe();
    const QString dataRoot = QStandardPaths::writableLocation(
        QStandardPaths::AppLocalDataLocation);
    QDir().mkpath(dataRoot);
    m_catalogPath = QDir(dataRoot).filePath(QStringLiteral("media-sources.json"));

    m_saveTimer.setSingleShot(true);
    m_saveTimer.setInterval(250);
    connect(&m_saveTimer, &QTimer::timeout, this, &MediaSourceModel::saveCatalog);

    loadCatalog();
}

MediaSourceModel::~MediaSourceModel()
{
    m_scanPool.waitForDone();
    m_probePool.waitForDone();
    if (m_saveTimer.isActive()) {
        m_saveTimer.stop();
        saveCatalog();
    }
}

int MediaSourceModel::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : m_assets.size();
}

QVariant MediaSourceModel::data(const QModelIndex &index, int role) const
{
    if (!index.isValid() || index.row() < 0 || index.row() >= m_assets.size())
        return {};

    const Asset &asset = m_assets.at(index.row());
    switch (role) {
    case AssetIdRole:
        return asset.id;
    case SourceUrlRole:
        return asset.sourceUrl;
    case PathRole:
        return asset.path;
    case NameRole:
        return asset.name;
    case KindRole:
        return asset.kind;
    case StatusRole:
        return asset.status;
    case StatusTextRole:
        if (asset.status == QStringLiteral("ready"))
            return QStringLiteral("Ready");
        if (asset.status == QStringLiteral("probing"))
            return QStringLiteral("Reading metadata");
        if (asset.status == QStringLiteral("queued"))
            return QStringLiteral("Queued");
        if (asset.status == QStringLiteral("missing"))
            return QStringLiteral("Source missing");
        return QStringLiteral("Probe failed");
    case SizeBytesRole:
        return QVariant::fromValue(asset.sizeBytes);
    case SizeTextRole:
        return formatBytes(asset.sizeBytes);
    case DimensionsRole:
        return asset.width > 0 && asset.height > 0
                   ? QStringLiteral("%1 × %2").arg(asset.width).arg(asset.height)
                   : QStringLiteral("—");
    case DurationSecondsRole:
        return asset.durationSeconds;
    case DurationTextRole:
        return formatDuration(asset.durationSeconds);
    case FramesPerSecondRole:
        return asset.framesPerSecond;
    case FramesPerSecondTextRole:
        return formatFramesPerSecond(asset.framesPerSecond);
    case FrameCountRole:
        return asset.frameCount;
    case CodecRole:
        return asset.codec;
    case ContainerRole:
        return asset.container;
    case PixelFormatRole:
        return asset.pixelFormat;
    case ColorDescriptionRole:
        return asset.colorDescription;
    case RotationRole:
        return asset.rotation;
    case FingerprintRole:
        return asset.fingerprint;
    case ErrorTextRole:
        return asset.errorText;
    default:
        return {};
    }
}

QHash<int, QByteArray> MediaSourceModel::roleNames() const
{
    return {
        { AssetIdRole, "assetId" },
        { SourceUrlRole, "sourceUrl" },
        { PathRole, "sourcePath" },
        { NameRole, "sourceName" },
        { KindRole, "mediaKind" },
        { StatusRole, "probeStatus" },
        { StatusTextRole, "probeStatusText" },
        { SizeBytesRole, "sizeBytes" },
        { SizeTextRole, "sizeText" },
        { DimensionsRole, "dimensionsText" },
        { DurationSecondsRole, "durationSeconds" },
        { DurationTextRole, "durationText" },
        { FramesPerSecondRole, "framesPerSecond" },
        { FramesPerSecondTextRole, "framesPerSecondText" },
        { FrameCountRole, "frameCount" },
        { CodecRole, "codecName" },
        { ContainerRole, "containerName" },
        { PixelFormatRole, "pixelFormat" },
        { ColorDescriptionRole, "colorDescription" },
        { RotationRole, "rotationDegrees" },
        { FingerprintRole, "fingerprint" },
        { ErrorTextRole, "probeError" }
    };
}

int MediaSourceModel::count() const
{
    return m_assets.size();
}

int MediaSourceModel::readyCount() const
{
    int result = 0;
    for (const Asset &asset : m_assets)
        result += asset.status == QStringLiteral("ready");
    return result;
}

int MediaSourceModel::errorCount() const
{
    int result = 0;
    for (const Asset &asset : m_assets) {
        result += asset.status == QStringLiteral("error")
                  || asset.status == QStringLiteral("missing");
    }
    return result;
}

int MediaSourceModel::busyCount() const
{
    int result = m_activeFolderScans;
    for (const Asset &asset : m_assets) {
        result += asset.status == QStringLiteral("queued")
                  || asset.status == QStringLiteral("probing");
    }
    return result;
}

bool MediaSourceModel::busy() const
{
    return busyCount() > 0;
}

quint64 MediaSourceModel::totalBytes() const
{
    quint64 result = 0;
    for (const Asset &asset : m_assets)
        result += asset.sizeBytes;
    return result;
}

QString MediaSourceModel::totalBytesText() const
{
    return formatBytes(totalBytes());
}

quint64 MediaSourceModel::readyBytes() const
{
    quint64 result = 0;
    for (const Asset &asset : m_assets) {
        if (asset.status == QStringLiteral("ready"))
            result += asset.sizeBytes;
    }
    return result;
}

QString MediaSourceModel::readyBytesText() const
{
    return formatBytes(readyBytes());
}

bool MediaSourceModel::ffprobeAvailable() const
{
    return !m_ffprobePath.isEmpty();
}

QString MediaSourceModel::ffprobePath() const
{
    return m_ffprobePath;
}

QString MediaSourceModel::catalogPath() const
{
    return m_catalogPath;
}

QString MediaSourceModel::activityText() const
{
    return m_activityText;
}

QString MediaSourceModel::lastError() const
{
    return m_lastError;
}

void MediaSourceModel::addUrls(const QVariantList &urls)
{
    for (const QVariant &value : urls) {
        QUrl url = value.toUrl();
        if (!url.isValid() || url.isEmpty())
            url = QUrl(value.toString());
        addUrl(url);
    }
}

void MediaSourceModel::addUrl(const QUrl &url)
{
    if (!url.isValid() || url.isEmpty()) {
        setLastError(QStringLiteral("The selected source URL is invalid."));
        return;
    }

    const QString path = url.isLocalFile() ? url.toLocalFile() : url.toString();
    enqueuePath(path);
}

void MediaSourceModel::retry(int row)
{
    if (row < 0 || row >= m_assets.size())
        return;

    Asset &asset = m_assets[row];
    const QFileInfo info(asset.path);
    if (!info.exists() || !info.isFile()) {
        asset.status = QStringLiteral("missing");
        asset.errorText = QStringLiteral("The source file is no longer available at this path.");
        emit dataChanged(index(row), index(row));
        emit summaryChanged();
        scheduleSave();
        return;
    }

    scheduleProbe(asset.id);
}

void MediaSourceModel::removeReference(int row)
{
    if (row < 0 || row >= m_assets.size())
        return;

    beginRemoveRows({}, row, row);
    m_assets.removeAt(row);
    endRemoveRows();
    emit summaryChanged();
    updateActivity();
    scheduleSave();
}

void MediaSourceModel::clearLastError()
{
    setLastError({});
}

QVariantList MediaSourceModel::readySources() const
{
    QVariantList result;
    result.reserve(readyCount());
    for (const Asset &asset : m_assets) {
        if (asset.status != QStringLiteral("ready"))
            continue;
        QVariantMap source;
        source.insert(QStringLiteral("assetId"), asset.id);
        source.insert(QStringLiteral("path"), asset.path);
        source.insert(QStringLiteral("kind"), asset.kind);
        source.insert(QStringLiteral("sizeBytes"), QString::number(asset.sizeBytes));
        source.insert(QStringLiteral("width"), asset.width);
        source.insert(QStringLiteral("height"), asset.height);
        source.insert(QStringLiteral("durationSeconds"), asset.durationSeconds);
        source.insert(QStringLiteral("framesPerSecond"), asset.framesPerSecond);
        source.insert(QStringLiteral("frameCount"), QString::number(asset.frameCount));
        source.insert(QStringLiteral("codec"), asset.codec);
        source.insert(QStringLiteral("container"), asset.container);
        source.insert(QStringLiteral("pixelFormat"), asset.pixelFormat);
        source.insert(QStringLiteral("colorDescription"), asset.colorDescription);
        source.insert(QStringLiteral("rotationDegrees"), asset.rotation);
        source.insert(QStringLiteral("catalogFingerprint"), asset.fingerprint);
        result.append(source);
    }
    return result;
}

void MediaSourceModel::loadCatalog()
{
    QFile file(m_catalogPath);
    if (!file.exists())
        return;
    if (!file.open(QIODevice::ReadOnly)) {
        setLastError(QStringLiteral("Unable to read the media source catalog: %1")
                         .arg(file.errorString()));
        return;
    }

    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(file.readAll(), &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
        setLastError(QStringLiteral("The media source catalog is invalid JSON: %1")
                         .arg(parseError.errorString()));
        return;
    }

    const QJsonObject root = document.object();
    if (root.value(QStringLiteral("schema")).toString()
        != QStringLiteral("servo.media-sources/v1")) {
        setLastError(QStringLiteral("The media source catalog uses an unsupported schema."));
        return;
    }

    const QJsonArray entries = root.value(QStringLiteral("sources")).toArray();
    QStringList pendingIds;
    beginResetModel();
    m_assets.clear();
    m_assets.reserve(entries.size());

    for (const QJsonValue &entryValue : entries) {
        const QJsonObject entry = entryValue.toObject();
        Asset asset;
        asset.id = entry.value(QStringLiteral("id")).toString();
        asset.path = normalizedPath(entry.value(QStringLiteral("path")).toString());
        if (asset.id.isEmpty() || asset.path.isEmpty())
            continue;

        asset.sourceUrl = QUrl::fromLocalFile(asset.path);
        asset.name = QFileInfo(asset.path).fileName();
        asset.kind = entry.value(QStringLiteral("kind")).toString(
            QStringLiteral("media"));
        asset.status = entry.value(QStringLiteral("status")).toString(
            QStringLiteral("queued"));
        asset.sizeBytes = entry.value(QStringLiteral("sizeBytes"))
                              .toString()
                              .toULongLong();
        asset.modifiedMilliseconds = entry.value(QStringLiteral("modifiedMilliseconds"))
                                         .toString()
                                         .toLongLong();
        asset.width = entry.value(QStringLiteral("width")).toInt();
        asset.height = entry.value(QStringLiteral("height")).toInt();
        asset.durationSeconds = jsonNumber(entry.value(QStringLiteral("durationSeconds")));
        asset.framesPerSecond = jsonNumber(entry.value(QStringLiteral("framesPerSecond")));
        asset.frameCount = jsonInteger(entry.value(QStringLiteral("frameCount")));
        asset.codec = entry.value(QStringLiteral("codec")).toString();
        asset.container = entry.value(QStringLiteral("container")).toString();
        asset.pixelFormat = entry.value(QStringLiteral("pixelFormat")).toString();
        asset.colorDescription = entry.value(QStringLiteral("colorDescription")).toString();
        asset.rotation = entry.value(QStringLiteral("rotation")).toInt();
        asset.fingerprint = entry.value(QStringLiteral("fingerprint")).toString();
        asset.errorText = entry.value(QStringLiteral("error")).toString();

        const QFileInfo info(asset.path);
        if (!info.exists() || !info.isFile()) {
            asset.status = QStringLiteral("missing");
            asset.errorText = QStringLiteral("The source file is no longer available at this path.");
        } else if (asset.status == QStringLiteral("probing")
                   || asset.status == QStringLiteral("queued")
                   || asset.status == QStringLiteral("missing")
                   || asset.sizeBytes != static_cast<quint64>(info.size())
                   || asset.modifiedMilliseconds
                          != info.lastModified().toMSecsSinceEpoch()) {
            asset.status = QStringLiteral("queued");
            asset.errorText.clear();
            pendingIds.append(asset.id);
        }

        m_assets.append(asset);
    }
    endResetModel();

    emit summaryChanged();
    for (const QString &id : std::as_const(pendingIds))
        scheduleProbe(id);
}

void MediaSourceModel::scheduleSave()
{
    m_saveTimer.start();
}

void MediaSourceModel::saveCatalog()
{
    QJsonArray entries;
    for (const Asset &asset : std::as_const(m_assets)) {
        QJsonObject entry;
        entry.insert(QStringLiteral("id"), asset.id);
        entry.insert(QStringLiteral("path"), asset.path);
        entry.insert(QStringLiteral("kind"), asset.kind);
        entry.insert(QStringLiteral("status"), asset.status);
        entry.insert(QStringLiteral("sizeBytes"), QString::number(asset.sizeBytes));
        entry.insert(QStringLiteral("modifiedMilliseconds"),
                     QString::number(asset.modifiedMilliseconds));
        entry.insert(QStringLiteral("width"), asset.width);
        entry.insert(QStringLiteral("height"), asset.height);
        entry.insert(QStringLiteral("durationSeconds"), asset.durationSeconds);
        entry.insert(QStringLiteral("framesPerSecond"), asset.framesPerSecond);
        entry.insert(QStringLiteral("frameCount"), QString::number(asset.frameCount));
        entry.insert(QStringLiteral("codec"), asset.codec);
        entry.insert(QStringLiteral("container"), asset.container);
        entry.insert(QStringLiteral("pixelFormat"), asset.pixelFormat);
        entry.insert(QStringLiteral("colorDescription"), asset.colorDescription);
        entry.insert(QStringLiteral("rotation"), asset.rotation);
        entry.insert(QStringLiteral("fingerprint"), asset.fingerprint);
        entry.insert(QStringLiteral("error"), asset.errorText);
        entries.append(entry);
    }

    QJsonObject root;
    root.insert(QStringLiteral("schema"), QStringLiteral("servo.media-sources/v1"));
    root.insert(QStringLiteral("updatedAt"),
                QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs));
    root.insert(QStringLiteral("sources"), entries);

    QSaveFile file(m_catalogPath);
    if (!file.open(QIODevice::WriteOnly)) {
        setLastError(QStringLiteral("Unable to save the media source catalog: %1")
                         .arg(file.errorString()));
        return;
    }

    if (file.write(QJsonDocument(root).toJson(QJsonDocument::Indented)) < 0
        || !file.commit()) {
        setLastError(QStringLiteral("Unable to commit the media source catalog: %1")
                         .arg(file.errorString()));
    }
}

void MediaSourceModel::enqueuePath(const QString &path)
{
    const QFileInfo info(path);
    if (!info.exists()) {
        setLastError(QStringLiteral("The selected source does not exist: %1").arg(path));
        return;
    }
    if (info.isDir()) {
        scanFolder(info.absoluteFilePath());
        return;
    }
    if (!info.isFile()) {
        setLastError(QStringLiteral("The selected source is not a regular file: %1")
                         .arg(path));
        return;
    }
    enqueueFile(info.absoluteFilePath());
}

void MediaSourceModel::enqueueFile(const QString &path)
{
    const QString cleanPath = normalizedPath(path);
    if (cleanPath.isEmpty())
        return;

    const int existingRow = rowForPath(cleanPath);
    if (existingRow >= 0) {
        if (m_assets.at(existingRow).status == QStringLiteral("missing"))
            retry(existingRow);
        return;
    }

    const QFileInfo info(cleanPath);
    Asset asset;
    asset.id = QUuid::createUuid().toString(QUuid::WithoutBraces);
    asset.sourceUrl = QUrl::fromLocalFile(cleanPath);
    asset.path = cleanPath;
    asset.name = info.fileName();
    asset.sizeBytes = static_cast<quint64>(info.size());
    asset.modifiedMilliseconds = info.lastModified().toMSecsSinceEpoch();

    const int row = m_assets.size();
    beginInsertRows({}, row, row);
    m_assets.append(asset);
    endInsertRows();
    emit summaryChanged();
    scheduleSave();
    scheduleProbe(asset.id);
}

void MediaSourceModel::scanFolder(const QString &path)
{
    ++m_activeFolderScans;
    updateActivity();
    emit summaryChanged();

    auto *watcher = new QFutureWatcher<QStringList>(this);
    connect(watcher, &QFutureWatcher<QStringList>::finished, this, [this, watcher]() {
        const QStringList paths = watcher->result();
        watcher->deleteLater();
        m_activeFolderScans = qMax(0, m_activeFolderScans - 1);

        for (const QString &path : paths)
            enqueueFile(path);

        if (paths.isEmpty())
            setLastError(QStringLiteral("No supported image or video files were found in the selected folder."));
        updateActivity();
        emit summaryChanged();
    });

    const QSet<QString> extensions = m_folderExtensions;
    watcher->setFuture(QtConcurrent::run(&m_scanPool, [path, extensions]() {
        QStringList result;
        QDirIterator iterator(path,
                              QDir::Files | QDir::Readable | QDir::NoDotAndDotDot,
                              QDirIterator::Subdirectories);
        while (iterator.hasNext()) {
            const QString candidate = iterator.next();
            if (extensions.contains(QFileInfo(candidate).suffix().toLower()))
                result.append(candidate);
        }
        return result;
    }));
}

void MediaSourceModel::scheduleProbe(const QString &assetId)
{
    const int row = rowForId(assetId);
    if (row < 0)
        return;

    refreshFfprobe();
    Asset &asset = m_assets[row];
    asset.status = QStringLiteral("probing");
    asset.errorText.clear();
    emit dataChanged(index(row), index(row));
    emit summaryChanged();
    updateActivity();

    const QString path = asset.path;
    const QString ffprobeExecutable = m_ffprobePath;
    const QSet<QString> imageExtensions = m_imageExtensions;
    auto *watcher = new QFutureWatcher<ProbeResult>(this);
    connect(watcher,
            &QFutureWatcher<ProbeResult>::finished,
            this,
            [this, watcher, assetId]() {
                const ProbeResult result = watcher->result();
                watcher->deleteLater();
                applyProbeResult(assetId, result);
            });
    watcher->setFuture(QtConcurrent::run(
        &m_probePool,
        [path, ffprobeExecutable, imageExtensions]() {
            return probeFile(path, ffprobeExecutable, imageExtensions);
        }));
}

void MediaSourceModel::refreshFfprobe()
{
    const QString nextPath = QStandardPaths::findExecutable(QStringLiteral("ffprobe"));
    if (nextPath == m_ffprobePath)
        return;
    m_ffprobePath = nextPath;
    emit ffprobeChanged();
}

int MediaSourceModel::rowForId(const QString &assetId) const
{
    for (int row = 0; row < m_assets.size(); ++row) {
        if (m_assets.at(row).id == assetId)
            return row;
    }
    return -1;
}

int MediaSourceModel::rowForPath(const QString &path) const
{
#ifdef Q_OS_WIN
    constexpr Qt::CaseSensitivity sensitivity = Qt::CaseInsensitive;
#else
    constexpr Qt::CaseSensitivity sensitivity = Qt::CaseSensitive;
#endif
    for (int row = 0; row < m_assets.size(); ++row) {
        if (QString::compare(m_assets.at(row).path, path, sensitivity) == 0)
            return row;
    }
    return -1;
}

void MediaSourceModel::applyProbeResult(const QString &assetId,
                                        const ProbeResult &result)
{
    const int row = rowForId(assetId);
    if (row < 0)
        return;

    Asset &asset = m_assets[row];
    asset.kind = result.kind;
    asset.status = result.success ? QStringLiteral("ready")
                                  : QStringLiteral("error");
    asset.sizeBytes = result.sizeBytes;
    asset.modifiedMilliseconds = result.modifiedMilliseconds;
    asset.width = result.width;
    asset.height = result.height;
    asset.durationSeconds = result.durationSeconds;
    asset.framesPerSecond = result.framesPerSecond;
    asset.frameCount = result.frameCount;
    asset.codec = result.codec;
    asset.container = result.container;
    asset.pixelFormat = result.pixelFormat;
    asset.colorDescription = result.colorDescription;
    asset.rotation = result.rotation;
    asset.fingerprint = result.fingerprint;
    asset.errorText = result.errorText;

    emit dataChanged(index(row), index(row));
    emit summaryChanged();
    updateActivity();
    scheduleSave();
}

void MediaSourceModel::updateActivity()
{
    QString nextActivity;
    if (m_activeFolderScans > 0) {
        nextActivity = m_activeFolderScans == 1
                           ? QStringLiteral("Scanning folder")
                           : QStringLiteral("Scanning %1 folders")
                                 .arg(m_activeFolderScans);
    } else {
        int activeProbes = 0;
        for (const Asset &asset : std::as_const(m_assets))
            activeProbes += asset.status == QStringLiteral("probing");
        if (activeProbes > 0) {
            nextActivity = activeProbes == 1
                               ? QStringLiteral("Reading source metadata")
                               : QStringLiteral("Reading %1 source headers")
                                     .arg(activeProbes);
        }
    }

    if (m_activityText == nextActivity)
        return;
    m_activityText = nextActivity;
    emit activityChanged();
}

void MediaSourceModel::setLastError(const QString &message)
{
    if (m_lastError == message)
        return;
    m_lastError = message;
    emit lastErrorChanged();
}

bool MediaSourceModel::isFolderCandidate(const QString &path) const
{
    return m_folderExtensions.contains(QFileInfo(path).suffix().toLower());
}

QString MediaSourceModel::normalizedPath(const QString &path)
{
    const QFileInfo info(path);
    QString result = info.canonicalFilePath();
    if (result.isEmpty())
        result = info.absoluteFilePath();
    return QDir::cleanPath(result);
}

QString MediaSourceModel::formatBytes(quint64 bytes)
{
    static const QStringList units { QStringLiteral("B"),
                                     QStringLiteral("KiB"),
                                     QStringLiteral("MiB"),
                                     QStringLiteral("GiB"),
                                     QStringLiteral("TiB"),
                                     QStringLiteral("PiB") };
    double value = static_cast<double>(bytes);
    int unit = 0;
    while (value >= 1024.0 && unit < units.size() - 1) {
        value /= 1024.0;
        ++unit;
    }
    const int precision = unit == 0 ? 0 : (value < 10.0 ? 2 : 1);
    return QStringLiteral("%1 %2").arg(value, 0, 'f', precision).arg(units.at(unit));
}

QString MediaSourceModel::formatDuration(double seconds)
{
    if (!std::isfinite(seconds) || seconds < 0.0)
        return QStringLiteral("—");

    const qint64 rounded = qRound64(seconds);
    const qint64 hours = rounded / 3600;
    const qint64 minutes = (rounded % 3600) / 60;
    const qint64 remainingSeconds = rounded % 60;
    if (hours > 0) {
        return QStringLiteral("%1:%2:%3")
            .arg(hours)
            .arg(minutes, 2, 10, QLatin1Char('0'))
            .arg(remainingSeconds, 2, 10, QLatin1Char('0'));
    }
    return QStringLiteral("%1:%2")
        .arg(minutes)
        .arg(remainingSeconds, 2, 10, QLatin1Char('0'));
}

QString MediaSourceModel::formatFramesPerSecond(double framesPerSecond)
{
    if (!std::isfinite(framesPerSecond) || framesPerSecond <= 0.0)
        return QStringLiteral("—");
    return QStringLiteral("%1 fps").arg(framesPerSecond, 0, 'f',
                                         framesPerSecond < 10.0 ? 2 : 3);
}

MediaSourceModel::ProbeResult MediaSourceModel::probeFile(
    const QString &path,
    const QString &ffprobeExecutable,
    const QSet<QString> &imageExtensions)
{
    ProbeResult result;
    const QFileInfo info(path);
    if (!info.exists() || !info.isFile()) {
        result.errorText = QStringLiteral("The source file is no longer available.");
        return result;
    }

    result.sizeBytes = static_cast<quint64>(info.size());
    result.modifiedMilliseconds = info.lastModified().toMSecsSinceEpoch();
    result.fingerprint = sampledFingerprint(path, result.sizeBytes);

    const QString suffix = info.suffix().toLower();
    if (imageExtensions.contains(suffix)) {
        QImageReader reader(path);
        reader.setAutoTransform(true);
        if (reader.canRead()) {
            const QSize dimensions = reader.size();
            if (dimensions.isValid()) {
                result.success = true;
                result.kind = QStringLiteral("image");
                result.width = dimensions.width();
                result.height = dimensions.height();
                result.frameCount = 1;
                result.codec = QString::fromLatin1(reader.format()).toLower();
                result.container = result.codec;
                return result;
            }
        }
    }

    if (ffprobeExecutable.isEmpty()) {
        result.errorText = QStringLiteral(
            "ffprobe was not found. Install or bundle FFmpeg to inspect video sources.");
        return result;
    }

    QProcess process;
    process.setProgram(ffprobeExecutable);
    process.setArguments({ QStringLiteral("-v"),
                           QStringLiteral("error"),
                           QStringLiteral("-print_format"),
                           QStringLiteral("json"),
                           QStringLiteral("-show_error"),
                           QStringLiteral("-show_format"),
                           QStringLiteral("-show_streams"),
                           QStringLiteral("-show_chapters"),
                           path });
    process.start(QIODevice::ReadOnly);
    if (!process.waitForStarted(5000)) {
        result.errorText = QStringLiteral("Unable to start ffprobe: %1")
                               .arg(process.errorString());
        return result;
    }
    if (!process.waitForFinished(probeTimeoutMilliseconds)) {
        process.kill();
        process.waitForFinished(5000);
        result.errorText = QStringLiteral("ffprobe did not finish within 120 seconds.");
        return result;
    }

    const QByteArray standardOutput = process.readAllStandardOutput();
    const QString standardError = QString::fromUtf8(process.readAllStandardError()).trimmed();
    if (process.exitStatus() != QProcess::NormalExit || process.exitCode() != 0) {
        result.errorText = standardError.isEmpty()
                               ? (process.exitStatus() == QProcess::CrashExit
                                      ? QStringLiteral("ffprobe crashed while inspecting the source.")
                                      : QStringLiteral("ffprobe exited with code %1.")
                                            .arg(process.exitCode()))
                               : standardError;
        return result;
    }
    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(standardOutput, &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
        result.errorText = standardError.isEmpty()
                               ? QStringLiteral("ffprobe returned invalid JSON: %1")
                                     .arg(parseError.errorString())
                               : standardError;
        return result;
    }

    const QJsonObject root = document.object();
    QJsonObject videoStream;
    qint64 bestPixelCount = -1;
    const QJsonArray streams = root.value(QStringLiteral("streams")).toArray();
    for (const QJsonValue &streamValue : streams) {
        const QJsonObject stream = streamValue.toObject();
        if (stream.value(QStringLiteral("codec_type")).toString()
            != QStringLiteral("video")) {
            continue;
        }
        const QJsonObject disposition = stream.value(QStringLiteral("disposition")).toObject();
        const QJsonValue attachedPicture = disposition.value(QStringLiteral("attached_pic"));
        const bool isAttachedPicture = attachedPicture.toBool(false)
                                       || attachedPicture.toInt(0) != 0;
        const int width = stream.value(QStringLiteral("width")).toInt();
        const int height = stream.value(QStringLiteral("height")).toInt();
        if (isAttachedPicture || width <= 0 || height <= 0)
            continue;
        const qint64 pixelCount = static_cast<qint64>(width) * height;
        if (pixelCount > bestPixelCount) {
            videoStream = stream;
            bestPixelCount = pixelCount;
        }
    }

    if (videoStream.isEmpty()) {
        const QJsonObject error = root.value(QStringLiteral("error")).toObject();
        result.errorText = error.value(QStringLiteral("string")).toString();
        if (result.errorText.isEmpty())
            result.errorText = standardError;
        if (result.errorText.isEmpty())
            result.errorText = QStringLiteral("No visual image or video stream was found.");
        return result;
    }

    const QJsonObject format = root.value(QStringLiteral("format")).toObject();
    result.success = true;
    result.kind = imageExtensions.contains(suffix) ? QStringLiteral("image")
                                                   : QStringLiteral("video");
    result.width = videoStream.value(QStringLiteral("width")).toInt();
    result.height = videoStream.value(QStringLiteral("height")).toInt();
    result.codec = videoStream.value(QStringLiteral("codec_name")).toString();
    result.container = format.value(QStringLiteral("format_name")).toString();
    result.pixelFormat = videoStream.value(QStringLiteral("pix_fmt")).toString();
    result.durationSeconds = jsonNumber(videoStream.value(QStringLiteral("duration")));
    if (result.durationSeconds < 0.0)
        result.durationSeconds = jsonNumber(format.value(QStringLiteral("duration")));
    result.frameCount = jsonInteger(videoStream.value(QStringLiteral("nb_frames")));
    result.framesPerSecond = rationalValue(
        videoStream.value(QStringLiteral("avg_frame_rate")).toString());
    if (result.framesPerSecond <= 0.0) {
        result.framesPerSecond = rationalValue(
            videoStream.value(QStringLiteral("r_frame_rate")).toString());
    }

    const QJsonObject tags = videoStream.value(QStringLiteral("tags")).toObject();
    result.rotation = static_cast<int>(std::lround(
        jsonNumber(tags.value(QStringLiteral("rotate")), 0.0)));
    const QJsonArray sideData = videoStream.value(QStringLiteral("side_data_list")).toArray();
    for (const QJsonValue &sideDataValue : sideData) {
        const QJsonObject sideDataObject = sideDataValue.toObject();
        if (sideDataObject.contains(QStringLiteral("rotation"))) {
            result.rotation = static_cast<int>(std::lround(
                jsonNumber(sideDataObject.value(QStringLiteral("rotation")),
                           result.rotation)));
            break;
        }
    }

    QStringList colorParts;
    const QString primaries = firstNonEmpty(
        videoStream,
        { "color_primaries", "color_space" });
    const QString transfer = firstNonEmpty(videoStream, { "color_transfer" });
    const QString range = firstNonEmpty(videoStream, { "color_range" });
    if (!primaries.isEmpty())
        colorParts.append(primaries);
    if (!transfer.isEmpty())
        colorParts.append(transfer);
    if (!range.isEmpty())
        colorParts.append(range);
    result.colorDescription = colorParts.join(QStringLiteral(" · "));

    if (result.kind == QStringLiteral("image")) {
        result.frameCount = 1;
        result.durationSeconds = -1.0;
        result.framesPerSecond = -1.0;
    }

    return result;
}
