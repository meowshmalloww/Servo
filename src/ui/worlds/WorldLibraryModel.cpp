#include "WorldLibraryModel.h"
#include "../reconstruction/ReconstructionPaths.h"

#include <QDesktopServices>
#include <QDir>
#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLocale>
#include <QSaveFile>
#include <QTimer>
#include <QtConcurrentRun>

#include <algorithm>
#include <filesystem>
#include <limits>
#include <utility>

namespace {
constexpr auto worldSchema = "servo.gaussian-world/v1";
constexpr auto catalogSchema = "servo.world-library/v1";
// Version 7 selects the best published visual-route world by manifest quality
// instead of naming a map or experiment. This makes the default portable to
// any future capture while avoiding a newer rejected diagnostic. Version 7
// reapplies that policy after the short-lived v6 desktop build persisted the
// newest review-required diagnostic as the user's default.
constexpr int latestSelectionPolicyVersion = 7;
constexpr qint64 maximumJsonBytes = 16LL * 1024LL * 1024LL;
constexpr qint64 maximumEventLogBytes = 32LL * 1024LL * 1024LL;
constexpr qint64 maximumEventLineBytes = 16LL * 1024LL * 1024LL;

#ifdef Q_OS_WIN
constexpr Qt::CaseSensitivity pathSensitivity = Qt::CaseInsensitive;
#else
constexpr Qt::CaseSensitivity pathSensitivity = Qt::CaseSensitive;
#endif

bool readJsonObject(const QString &path, QJsonObject *result)
{
    QFile file(path);
    if (!file.exists() || file.size() <= 0 || file.size() > maximumJsonBytes
        || !file.open(QIODevice::ReadOnly)) {
        return false;
    }

    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(file.readAll(), &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject())
        return false;
    if (result)
        *result = document.object();
    return true;
}

QString canonicalOrAbsolute(const QString &path)
{
    const QFileInfo info(path);
    QString result = info.canonicalFilePath();
    if (result.isEmpty())
        result = info.absoluteFilePath();
    return QDir::cleanPath(result);
}

bool samePath(const QString &left, const QString &right)
{
    return QString::compare(QDir::cleanPath(left),
                            QDir::cleanPath(right),
                            pathSensitivity)
           == 0;
}

bool pathInside(const QString &root, const QString &candidate)
{
    const QString cleanRoot = QDir::cleanPath(root);
    const QString cleanCandidate = QDir::cleanPath(candidate);
    if (cleanRoot.isEmpty() || cleanCandidate.isEmpty())
        return false;
    if (samePath(cleanRoot, cleanCandidate))
        return true;
    return cleanCandidate.startsWith(cleanRoot + QLatin1Char('/'), pathSensitivity);
}

QString resolveExistingPath(const QString &root, const QString &relativePath)
{
    if (relativePath.isEmpty() || QDir::isAbsolutePath(relativePath))
        return {};
    const QString rootPath = canonicalOrAbsolute(root);
    const QString candidate = canonicalOrAbsolute(QDir(root).filePath(relativePath));
    if (!pathInside(rootPath, candidate))
        return {};
    return candidate;
}

qulonglong directorySize(const QString &path)
{
    qulonglong total = 0;
    QDirIterator iterator(path,
                          QDir::Files | QDir::Hidden | QDir::System
                              | QDir::NoDotAndDotDot,
                          QDirIterator::Subdirectories);
    while (iterator.hasNext()) {
        iterator.next();
        const QFileInfo info = iterator.fileInfo();
        if (info.isSymLink())
            continue;
        const qulonglong size = static_cast<qulonglong>(std::max<qint64>(0, info.size()));
        if (std::numeric_limits<qulonglong>::max() - total < size)
            return std::numeric_limits<qulonglong>::max();
        total += size;
    }
    return total;
}

QString sourceSummary(const QJsonArray &sources)
{
    if (sources.isEmpty())
        return QStringLiteral("Source unavailable");
    const QJsonObject first = sources.first().toObject();
    QString name = QFileInfo(first.value(QStringLiteral("path")).toString()).fileName();
    if (name.isEmpty())
        name = first.value(QStringLiteral("kind")).toString(QStringLiteral("Media"));
    if (sources.size() == 1)
        return name;
    return QStringLiteral("%1 + %2 more").arg(name).arg(sources.size() - 1);
}

QString firstPreview(const QString &worldPath, const QJsonObject &artifacts)
{
    QString relativeDirectory = artifacts.value(QStringLiteral("validationRenders")).toString();
    if (relativeDirectory.isEmpty())
        relativeDirectory = QStringLiteral("validation-renders");
    const QString directoryPath = resolveExistingPath(worldPath, relativeDirectory);
    const QFileInfo directoryInfo(directoryPath);
    if (directoryPath.isEmpty() || !directoryInfo.isDir())
        return {};

    const QFileInfoList images = QDir(directoryPath).entryInfoList(
        { QStringLiteral("compare-*.png"), QStringLiteral("*.png"), QStringLiteral("*.jpg") },
        QDir::Files | QDir::Readable | QDir::NoDotAndDotDot,
        QDir::Name);
    if (images.isEmpty())
        return {};
    const QString candidate = canonicalOrAbsolute(images.first().absoluteFilePath());
    return pathInside(canonicalOrAbsolute(worldPath), candidate) ? candidate : QString();
}

QString firstDiagnosticPreview(const QString &jobPath)
{
    const QString directoryPath = resolveExistingPath(
        jobPath, QStringLiteral("stages/train/validation"));
    const QFileInfo directoryInfo(directoryPath);
    if (directoryPath.isEmpty() || !directoryInfo.isDir())
        return {};

    const QFileInfoList images = QDir(directoryPath).entryInfoList(
        { QStringLiteral("compare-*.png"), QStringLiteral("*.png"), QStringLiteral("*.jpg") },
        QDir::Files | QDir::Readable | QDir::NoDotAndDotDot,
        QDir::Name);
    if (images.isEmpty())
        return {};
    const QString candidate = canonicalOrAbsolute(images.first().absoluteFilePath());
    return pathInside(canonicalOrAbsolute(jobPath), candidate) ? candidate : QString();
}

bool isTerminalFailedJob(const QString &jobPath)
{
    QFile events(QDir(jobPath).filePath(QStringLiteral("events.jsonl")));
    if (!events.exists() || events.size() <= 0 || events.size() > maximumEventLogBytes
        || !events.open(QIODevice::ReadOnly)) {
        return false;
    }

    QByteArray terminalEvent;
    while (!events.atEnd()) {
        const QByteArray line = events.readLine(maximumEventLineBytes + 1);
        if (line.size() > maximumEventLineBytes)
            return false;
        if (!line.trimmed().isEmpty())
            terminalEvent = line;
    }
    return terminalEvent.contains("\"event\":\"job_failed\"")
           && terminalEvent.contains("\"state\":\"failed\"");
}

qint64 jsonInteger(const QJsonValue &value, qint64 fallback = 0)
{
    if (value.isDouble())
        return value.toInteger(fallback);
    if (value.isString()) {
        bool valid = false;
        const qint64 result = value.toString().toLongLong(&valid);
        if (valid)
            return result;
    }
    return fallback;
}
} // namespace

struct WorldLibraryModel::WorldEntry {
    QString worldId;
    QString displayName;
    QString originalName;
    QString worldPath;
    QString plyPath;
    QString jobPath;
    QUrl previewUrl;
    QUrl repairedReferenceUrl;
    QString sourceSummary;
    QDateTime createdAt;
    QString createdText;
    QString profile;
    QString qualityTier;
    double psnr = -1.0;
    double ssim = -1.0;
    qint64 gaussianCount = 0;
    qulonglong sizeBytes = 0;
    QString representation;
    QString pipelineRevision;
    QString scaleText;
    bool published = true;
    QString failureText;
    QVariantList recordedFrameUrls;
    QVariantList routeTiles;
};

struct WorldLibraryModel::DeleteResult {
    bool success = false;
    QString error;
};

WorldLibraryModel::WorldLibraryModel(QObject *parent)
    : WorldLibraryModel(defaultJobsRoot(), defaultCatalogPath(), parent)
{
}

WorldLibraryModel::WorldLibraryModel(const QString &jobsRoot,
                                     const QString &catalogPath,
                                     QObject *parent)
    : QAbstractListModel(parent)
    , m_jobsRoot(QDir::cleanPath(QFileInfo(jobsRoot).absoluteFilePath()))
    , m_catalogPath(QDir::cleanPath(QFileInfo(catalogPath).absoluteFilePath()))
{
    loadCatalog();
    refresh();
}

WorldLibraryModel::~WorldLibraryModel() = default;

int WorldLibraryModel::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : m_visibleRows.size();
}

QVariant WorldLibraryModel::data(const QModelIndex &index, int role) const
{
    if (!index.isValid() || index.row() < 0 || index.row() >= m_visibleRows.size())
        return {};
    const WorldEntry &entry = m_worlds.at(m_visibleRows.at(index.row()));
    switch (role) {
    case Qt::DisplayRole:
    case DisplayNameRole:
        return entry.displayName;
    case WorldIdRole:
        return entry.worldId;
    case OriginalNameRole:
        return entry.originalName;
    case WorldPathRole:
        return entry.worldPath;
    case PlyPathRole:
        return entry.plyPath;
    case JobPathRole:
        return entry.jobPath;
    case PreviewUrlRole:
        return entry.previewUrl;
    case SourceSummaryRole:
        return entry.sourceSummary;
    case CreatedAtRole:
        return entry.createdAt.toUTC().toString(Qt::ISODateWithMs);
    case CreatedTextRole:
        return entry.createdText;
    case ProfileRole:
        return entry.profile;
    case ProfileLabelRole:
        return profileLabel(entry.profile);
    case QualityTierRole:
        return entry.qualityTier;
    case QualityLabelRole:
        return qualityLabel(entry.qualityTier);
    case QualityToneRole:
        return qualityTone(entry.qualityTier);
    case PsnrRole:
        return entry.psnr;
    case SsimRole:
        return entry.ssim;
    case GaussianCountRole:
        return entry.gaussianCount;
    case GaussianTextRole:
        return formatCount(entry.gaussianCount);
    case SizeBytesRole:
        return QVariant::fromValue(entry.sizeBytes);
    case SizeTextRole:
        return formatBytes(entry.sizeBytes);
    case RepresentationRole:
        return entry.representation;
    case PipelineRevisionRole:
        return entry.pipelineRevision;
    case ScaleTextRole:
        return entry.scaleText;
    case PublishedRole:
        return entry.published;
    case FailureTextRole:
        return entry.failureText;
    case RecordedFrameUrlsRole:
        return entry.recordedFrameUrls;
    case RecordedFrameCountRole:
        return entry.recordedFrameUrls.size();
    default:
        return {};
    }
}

QHash<int, QByteArray> WorldLibraryModel::roleNames() const
{
    return {
        { Qt::DisplayRole, "display" },
        { WorldIdRole, "worldId" },
        { DisplayNameRole, "displayName" },
        { OriginalNameRole, "originalName" },
        { WorldPathRole, "worldPath" },
        { PlyPathRole, "plyPath" },
        { JobPathRole, "jobPath" },
        { PreviewUrlRole, "previewUrl" },
        { SourceSummaryRole, "sourceSummary" },
        { CreatedAtRole, "createdAt" },
        { CreatedTextRole, "createdText" },
        { ProfileRole, "profile" },
        { ProfileLabelRole, "profileLabel" },
        { QualityTierRole, "qualityTier" },
        { QualityLabelRole, "qualityLabel" },
        { QualityToneRole, "qualityTone" },
        { PsnrRole, "psnr" },
        { SsimRole, "ssim" },
        { GaussianCountRole, "gaussianCount" },
        { GaussianTextRole, "gaussianText" },
        { SizeBytesRole, "sizeBytes" },
        { SizeTextRole, "sizeText" },
        { RepresentationRole, "representation" },
        { PipelineRevisionRole, "pipelineRevision" },
        { ScaleTextRole, "scaleText" },
        { PublishedRole, "published" },
        { FailureTextRole, "failureText" },
        { RecordedFrameUrlsRole, "recordedFrameUrls" },
        { RecordedFrameCountRole, "recordedFrameCount" },
    };
}

int WorldLibraryModel::count() const
{
    return m_visibleRows.size();
}

int WorldLibraryModel::totalCount() const
{
    return m_worlds.size();
}

qulonglong WorldLibraryModel::totalBytes() const
{
    qulonglong total = 0;
    for (const WorldEntry &entry : m_worlds) {
        if (std::numeric_limits<qulonglong>::max() - total < entry.sizeBytes)
            return std::numeric_limits<qulonglong>::max();
        total += entry.sizeBytes;
    }
    return total;
}

QString WorldLibraryModel::totalBytesText() const
{
    return formatBytes(totalBytes());
}

bool WorldLibraryModel::busy() const
{
    return m_refreshBusy || m_deleteBusy;
}

QString WorldLibraryModel::busyText() const
{
    if (m_deleteBusy)
        return QStringLiteral("Deleting %1").arg(m_deletingWorldName);
    if (m_refreshBusy)
        return QStringLiteral("Updating world library");
    return {};
}

QString WorldLibraryModel::filterText() const
{
    return m_filterText;
}

void WorldLibraryModel::setFilterText(const QString &value)
{
    if (m_filterText == value)
        return;
    m_filterText = value;
    beginResetModel();
    rebuildVisibleRows();
    endResetModel();
    emit filterTextChanged();
    emit summaryChanged();
    emit selectionChanged();
}

QString WorldLibraryModel::sortMode() const
{
    return m_sortMode;
}

void WorldLibraryModel::setSortMode(const QString &value)
{
    const QString normalized = value.toLower();
    if (normalized != QStringLiteral("newest")
        && normalized != QStringLiteral("name")
        && normalized != QStringLiteral("size")) {
        return;
    }
    if (m_sortMode == normalized)
        return;
    m_sortMode = normalized;
    beginResetModel();
    sortWorlds();
    rebuildVisibleRows();
    endResetModel();
    emit sortModeChanged();
    emit summaryChanged();
    emit selectionChanged();
}

QString WorldLibraryModel::selectedWorldId() const
{
    return m_selectedWorldId;
}

int WorldLibraryModel::selectedIndex() const
{
    return visibleRowForId(m_selectedWorldId);
}

bool WorldLibraryModel::hasSelection() const
{
    return rowForId(m_selectedWorldId) >= 0;
}

QVariantMap WorldLibraryModel::selectedWorld() const
{
    const int row = rowForId(m_selectedWorldId);
    return row >= 0 ? entryMap(m_worlds.at(row)) : QVariantMap();
}

QString WorldLibraryModel::jobsRoot() const
{
    return m_jobsRoot;
}

QString WorldLibraryModel::lastError() const
{
    return m_lastError;
}

void WorldLibraryModel::refresh()
{
    if (m_refreshBusy || m_deleteBusy) {
        m_refreshPending = true;
        return;
    }

    setRefreshBusy(true);
    const QString jobsPath = m_jobsRoot;
    const QHash<QString, QString> aliases = m_aliases;
    auto *watcher = new QFutureWatcher<QVector<WorldEntry>>(this);
    connect(watcher,
            &QFutureWatcher<QVector<WorldEntry>>::finished,
            this,
            [this, watcher]() {
                QVector<WorldEntry> worlds = watcher->result();
                watcher->deleteLater();
                applyScannedWorlds(std::move(worlds));
                setRefreshBusy(false);
                if (m_refreshPending) {
                    m_refreshPending = false;
                    QTimer::singleShot(0, this, &WorldLibraryModel::refresh);
                }
            });
    watcher->setFuture(QtConcurrent::run(
        [jobsPath, aliases]() { return scanJobs(jobsPath, aliases); }));
}

bool WorldLibraryModel::selectWorld(const QString &worldId)
{
    if (rowForId(worldId) < 0) {
        setLastError(QStringLiteral("That world is no longer in the local library."));
        return false;
    }
    setSelectedWorldId(worldId);
    return true;
}

bool WorldLibraryModel::selectWorldMatching(const QString &query)
{
    const QString needle = query.trimmed();
    if (needle.isEmpty())
        return false;
    for (const WorldEntry &entry : std::as_const(m_worlds)) {
        if (entry.worldId.contains(needle, Qt::CaseInsensitive)
            || entry.displayName.contains(needle, Qt::CaseInsensitive)
            || entry.originalName.contains(needle, Qt::CaseInsensitive)) {
            setSelectedWorldId(entry.worldId);
            return true;
        }
    }
    setLastError(QStringLiteral("No created world matches \"%1\".").arg(needle));
    return false;
}

void WorldLibraryModel::selectWorldPath(const QString &worldPath)
{
    const QString normalizedPath = canonicalOrAbsolute(worldPath);
    for (const WorldEntry &entry : std::as_const(m_worlds)) {
        if (samePath(entry.worldPath, normalizedPath)) {
            m_pendingWorldPath.clear();
            setSelectedWorldId(entry.worldId);
            return;
        }
    }
    m_pendingWorldPath = normalizedPath;
    refresh();
}

bool WorldLibraryModel::renameWorld(const QString &worldId,
                                    const QString &displayName)
{
    const int row = rowForId(worldId);
    if (row < 0) {
        setLastError(QStringLiteral("That world is no longer in the local library."));
        return false;
    }
    const QString sanitized = sanitizeDisplayName(displayName);
    if (sanitized.isEmpty()) {
        setLastError(QStringLiteral("Enter a world name between 1 and 80 characters."));
        return false;
    }

    WorldEntry &entry = m_worlds[row];
    if (entry.displayName == sanitized)
        return true;
    const QString previousName = entry.displayName;
    const QString previousAlias = m_aliases.value(worldId);
    entry.displayName = sanitized;
    if (sanitized == entry.originalName)
        m_aliases.remove(worldId);
    else
        m_aliases.insert(worldId, sanitized);

    if (!saveCatalog()) {
        entry.displayName = previousName;
        if (previousAlias.isEmpty())
            m_aliases.remove(worldId);
        else
            m_aliases.insert(worldId, previousAlias);
        return false;
    }

    if (m_sortMode == QStringLiteral("name")) {
        beginResetModel();
        sortWorlds();
        rebuildVisibleRows();
        endResetModel();
        emit summaryChanged();
    } else {
        const int visibleRow = visibleRowForId(worldId);
        if (visibleRow >= 0) {
            emit dataChanged(index(visibleRow),
                             index(visibleRow),
                             { Qt::DisplayRole, DisplayNameRole });
        }
    }
    emit selectionChanged();
    return true;
}

bool WorldLibraryModel::deleteWorld(const QString &worldId)
{
    if (m_deleteBusy) {
        setLastError(QStringLiteral("Wait for the current deletion to finish."));
        return false;
    }
    const int row = rowForId(worldId);
    if (row < 0) {
        setLastError(QStringLiteral("That world is no longer in the local library."));
        return false;
    }

    const WorldEntry entry = m_worlds.at(row);
    setDeleteBusy(true, entry.displayName);
    const QString jobsPath = m_jobsRoot;
    auto *watcher = new QFutureWatcher<DeleteResult>(this);
    connect(watcher,
            &QFutureWatcher<DeleteResult>::finished,
            this,
            [this, watcher, entry]() {
                const DeleteResult result = watcher->result();
                watcher->deleteLater();
                setDeleteBusy(false);
                if (result.success) {
                    m_aliases.remove(entry.worldId);
                    if (m_selectedWorldId == entry.worldId)
                        m_selectedWorldId.clear();
                    saveCatalog();
                    emit worldDeleted(entry.worldId,
                                      entry.displayName,
                                      entry.sizeBytes);
                } else {
                    setLastError(result.error);
                }
                refresh();
            });
    watcher->setFuture(QtConcurrent::run(
        [jobsPath, jobPath = entry.jobPath]() {
            return deleteJobTree(jobsPath, jobPath);
        }));
    return true;
}

void WorldLibraryModel::openWorldFolder(const QString &worldId)
{
    const int row = rowForId(worldId);
    if (row < 0) {
        setLastError(QStringLiteral("That world is no longer in the local library."));
        return;
    }
    if (!QDesktopServices::openUrl(QUrl::fromLocalFile(m_worlds.at(row).worldPath)))
        setLastError(QStringLiteral("Windows could not open the world bundle folder."));
}

void WorldLibraryModel::openJobFolder(const QString &worldId)
{
    const int row = rowForId(worldId);
    if (row < 0) {
        setLastError(QStringLiteral("That world is no longer in the local library."));
        return;
    }
    if (!QDesktopServices::openUrl(QUrl::fromLocalFile(m_worlds.at(row).jobPath)))
        setLastError(QStringLiteral("Windows could not open the reconstruction job folder."));
}

void WorldLibraryModel::clearLastError()
{
    setLastError({});
}

QString WorldLibraryModel::defaultJobsRoot()
{
    return QDir(Servo::ReconstructionPaths::localRuntimeRoot())
        .filePath(QStringLiteral("jobs"));
}

QString WorldLibraryModel::defaultCatalogPath()
{
    return QDir(Servo::ReconstructionPaths::localRuntimeRoot())
        .filePath(QStringLiteral("world-library.json"));
}

QVector<WorldLibraryModel::WorldEntry> WorldLibraryModel::scanJobs(
    const QString &jobsRoot,
    const QHash<QString, QString> &aliases)
{
    QVector<WorldEntry> result;
    const QDir root(jobsRoot);
    if (!root.exists())
        return result;

    const QFileInfoList jobDirectories = root.entryInfoList(
        QDir::Dirs | QDir::Readable | QDir::NoDotAndDotDot,
        QDir::Name);
    result.reserve(jobDirectories.size());
    for (const QFileInfo &jobDirectory : jobDirectories) {
        if (jobDirectory.isSymLink() || jobDirectory.isJunction())
            continue;

        const QString jobPath = canonicalOrAbsolute(jobDirectory.absoluteFilePath());
        QJsonObject job;
        if (!readJsonObject(QDir(jobPath).filePath(QStringLiteral("job.json")), &job))
            continue;
        const QString jobId = job.value(QStringLiteral("jobId")).toString();
        if (jobId.isEmpty()
            || QString::compare(jobId, jobDirectory.fileName(), Qt::CaseInsensitive) != 0) {
            continue;
        }

        const QString worldPath = canonicalOrAbsolute(
            QDir(jobPath).filePath(QStringLiteral("stages/publish/world")));
        QJsonObject manifest;
        const bool hasWorldManifest = readJsonObject(
                                          QDir(worldPath).filePath(QStringLiteral("world.json")),
                                          &manifest)
                                      && manifest.value(QStringLiteral("schema")).toString()
                                             == QLatin1StringView(worldSchema);
        if (!hasWorldManifest) {
            QJsonObject heldout;
            if (!readJsonObject(
                    QDir(jobPath).filePath(QStringLiteral("stages/train/heldout-metrics.json")),
                    &heldout)
                || heldout.value(QStringLiteral("schema")).toString()
                       != QLatin1StringView("servo.gsplat-heldout-evaluation/v1")
                || !isTerminalFailedJob(jobPath)) {
                continue;
            }

            WorldEntry entry;
            entry.worldId = jobId;
            entry.jobPath = jobPath;
            entry.worldPath = worldPath;
            entry.originalName = sanitizeDisplayName(
                job.value(QStringLiteral("worldName")).toString());
            if (entry.originalName.isEmpty())
                entry.originalName = QStringLiteral("World %1").arg(jobId.left(8));
            entry.displayName = sanitizeDisplayName(aliases.value(jobId));
            if (entry.displayName.isEmpty())
                entry.displayName = entry.originalName;
            entry.sourceSummary = sourceSummary(job.value(QStringLiteral("sources")).toArray());
            entry.createdAt = QDateTime::fromString(
                job.value(QStringLiteral("createdAt")).toString(), Qt::ISODateWithMs);
            if (!entry.createdAt.isValid())
                entry.createdAt = QFileInfo(QDir(jobPath).filePath(QStringLiteral("job.json")))
                                      .lastModified();
            entry.createdText = QLocale().toString(entry.createdAt.toLocalTime(),
                                                   QLocale::ShortFormat);
            entry.profile = job.value(QStringLiteral("profile")).toString();
            entry.qualityTier = QStringLiteral("failed");
            entry.psnr = heldout.value(QStringLiteral("psnrMean")).toDouble(-1.0);
            entry.ssim = heldout.value(QStringLiteral("ssimMean")).toDouble(-1.0);
            entry.representation = QStringLiteral("No publishable Gaussian world");
            entry.pipelineRevision = heldout.value(QStringLiteral("pipelineRevision")).toString();
            entry.scaleText = QStringLiteral("not exported");
            entry.published = false;
            entry.failureText = QStringLiteral(
                "Held-out quality gate failed; no publishable Gaussian world was exported.");
            const QString previewPath = firstDiagnosticPreview(jobPath);
            if (!previewPath.isEmpty())
                entry.previewUrl = QUrl::fromLocalFile(previewPath);
            entry.sizeBytes = directorySize(jobPath);
            result.append(std::move(entry));
            continue;
        }

        const QString worldId = manifest.value(QStringLiteral("worldId")).toString();
        if (worldId.isEmpty() || worldId != jobId) {
            continue;
        }

        const QJsonObject artifacts = manifest.value(QStringLiteral("artifacts")).toObject();
        const QString plyPath = resolveExistingPath(
            worldPath,
            artifacts.value(QStringLiteral("ply")).toString());
        const QFileInfo plyInfo(plyPath);
        if (plyPath.isEmpty() || !plyInfo.isFile() || !plyInfo.isReadable()
            || plyInfo.size() <= 0) {
            continue;
        }

        WorldEntry entry;
        entry.worldId = worldId;
        entry.jobPath = jobPath;
        entry.worldPath = worldPath;
        entry.plyPath = plyPath;
        entry.originalName = sanitizeDisplayName(
            job.value(QStringLiteral("worldName")).toString());
        if (entry.originalName.isEmpty())
            entry.originalName = QStringLiteral("World %1").arg(worldId.left(8));
        entry.displayName = sanitizeDisplayName(aliases.value(worldId));
        if (entry.displayName.isEmpty())
            entry.displayName = entry.originalName;
        entry.sourceSummary = sourceSummary(job.value(QStringLiteral("sources")).toArray());
        entry.createdAt = QDateTime::fromString(
            manifest.value(QStringLiteral("createdAt")).toString(),
            Qt::ISODateWithMs);
        if (!entry.createdAt.isValid()) {
            entry.createdAt = QDateTime::fromString(
                job.value(QStringLiteral("createdAt")).toString(),
                Qt::ISODateWithMs);
        }
        if (!entry.createdAt.isValid())
            entry.createdAt = QFileInfo(QDir(worldPath).filePath(QStringLiteral("world.json")))
                                  .lastModified();
        entry.createdText = QLocale().toString(entry.createdAt.toLocalTime(),
                                               QLocale::ShortFormat);
        entry.profile = manifest.value(QStringLiteral("profile"))
                            .toString(job.value(QStringLiteral("profile")).toString());
        const QJsonObject quality = manifest.value(QStringLiteral("quality")).toObject();
        const QJsonObject finalArtifact = quality.value(QStringLiteral("finalArtifact")).toObject();
        const QJsonObject heldout = quality.value(QStringLiteral("heldout")).toObject();
        const auto qualityMetric = [&quality, &finalArtifact, &heldout](const QString &name) {
            const QJsonValue directValue = quality.value(name);
            if (directValue.isDouble())
                return directValue.toDouble();
            const QJsonValue finalValue = finalArtifact.value(name);
            if (finalValue.isDouble())
                return finalValue.toDouble();
            const QJsonValue heldoutValue = heldout.value(name);
            return heldoutValue.isDouble() ? heldoutValue.toDouble() : -1.0;
        };
        entry.qualityTier = quality.value(QStringLiteral("tier"))
                                .toString(QStringLiteral("unrated"));
        entry.psnr = qualityMetric(QStringLiteral("psnrMean"));
        entry.ssim = qualityMetric(QStringLiteral("ssimMean"));
        entry.gaussianCount = jsonInteger(
            quality.value(QStringLiteral("cleanup")).toObject().value(
                QStringLiteral("retainedGaussians")));
        entry.representation = manifest.value(QStringLiteral("representationType"))
                                   .toString(QStringLiteral("3D Gaussian splats"));
        entry.pipelineRevision = manifest.value(QStringLiteral("pipelineRevision")).toString();
        entry.scaleText = manifest.value(QStringLiteral("coordinateSystem"))
                              .toObject()
                              .value(QStringLiteral("scale"))
                              .toString(QStringLiteral("unknown"));
        const QJsonArray routeTiles = manifest.value(QStringLiteral("routeTiles")).toArray();
        entry.routeTiles.reserve(routeTiles.size());
        for (const QJsonValue &tileValue : routeTiles) {
            const QJsonObject tile = tileValue.toObject();
            const QString tileId = tile.value(QStringLiteral("tileId")).toString();
            const QString tilePlyPath = resolveExistingPath(
                worldPath, tile.value(QStringLiteral("ply")).toString());
            const QFileInfo tilePly(tilePlyPath);
            if (tileId.isEmpty() || tilePlyPath.isEmpty() || !tilePly.isFile()
                || !tilePly.isReadable() || tilePly.size() <= 0) {
                entry.routeTiles.clear();
                break;
            }
            entry.routeTiles.append(QVariantMap {
                { QStringLiteral("tileId"), tileId },
                { QStringLiteral("plyPath"), tilePlyPath },
                { QStringLiteral("plyUrl"), QUrl::fromLocalFile(tilePlyPath) },
                { QStringLiteral("cameraStart"),
                  jsonInteger(tile.value(QStringLiteral("cameraStart"))) },
                { QStringLiteral("cameraEndExclusive"),
                  jsonInteger(tile.value(QStringLiteral("cameraEndExclusive"))) },
                { QStringLiteral("cameraCount"),
                  jsonInteger(tile.value(QStringLiteral("cameraCount"))) },
                { QStringLiteral("gaussianCount"),
                  jsonInteger(tile.value(QStringLiteral("gaussianCount"))) },
                { QStringLiteral("sourceProfile"),
                  tile.value(QStringLiteral("sourceProfile")).toString() },
            });
        }
        const QString camerasPath = resolveExistingPath(
            worldPath,
            artifacts.value(QStringLiteral("cameras")).toString(
                QStringLiteral("cameras.json")));
        const QString recordedImagesRoot = canonicalOrAbsolute(
            QDir(jobPath).filePath(QStringLiteral("stages/pose/training/images")));
        QJsonObject camerasDocument;
        if (!camerasPath.isEmpty()
            && QDir(recordedImagesRoot).exists()
            && readJsonObject(camerasPath, &camerasDocument)) {
            const QJsonArray cameras = camerasDocument.value(QStringLiteral("cameras")).toArray();
            entry.recordedFrameUrls.reserve(cameras.size());
            for (const QJsonValue &cameraValue : cameras) {
                const QString relativeImage = cameraValue.toObject()
                                                  .value(QStringLiteral("image"))
                                                  .toString();
                if (relativeImage.isEmpty() || QDir::isAbsolutePath(relativeImage))
                    continue;
                const QString candidate = canonicalOrAbsolute(
                    QDir(recordedImagesRoot).filePath(relativeImage));
                const QFileInfo image(candidate);
                if (pathInside(recordedImagesRoot, candidate)
                    && image.isFile() && image.isReadable()) {
                    entry.recordedFrameUrls.append(QUrl::fromLocalFile(candidate));
                }
            }
        }
        if (entry.recordedFrameUrls.isEmpty()) {
            const QString bundledFramesPath = resolveExistingPath(
                worldPath,
                artifacts.value(QStringLiteral("recordedFrames")).toString(
                    QStringLiteral("recorded-frames")));
            const QDir bundledFrames(bundledFramesPath);
            const QFileInfoList frames = bundledFrames.entryInfoList(
                { QStringLiteral("*.jpg"), QStringLiteral("*.jpeg"),
                  QStringLiteral("*.png") },
                QDir::Files | QDir::Readable | QDir::NoSymLinks,
                QDir::Name);
            entry.recordedFrameUrls.reserve(frames.size());
            for (const QFileInfo &frame : frames) {
                const QString candidate = canonicalOrAbsolute(frame.absoluteFilePath());
                if (pathInside(worldPath, candidate))
                    entry.recordedFrameUrls.append(QUrl::fromLocalFile(candidate));
            }
        }
        const QString previewPath = firstPreview(worldPath, artifacts);
        if (!previewPath.isEmpty())
            entry.previewUrl = QUrl::fromLocalFile(previewPath);
        const QString repairedReferencePath = resolveExistingPath(
            worldPath, artifacts.value(QStringLiteral("difixReference")).toString());
        if (!repairedReferencePath.isEmpty()) {
            const QFileInfo repairedReference(repairedReferencePath);
            if (pathInside(worldPath, repairedReferencePath)
                && repairedReference.isFile() && repairedReference.isReadable()) {
                entry.repairedReferenceUrl = QUrl::fromLocalFile(repairedReferencePath);
            }
        }
        entry.sizeBytes = directorySize(jobPath);
        result.append(std::move(entry));
    }
    return result;
}

WorldLibraryModel::DeleteResult WorldLibraryModel::deleteJobTree(
    const QString &jobsRoot,
    const QString &jobPath)
{
    DeleteResult result;
    const QFileInfo rootInfo(jobsRoot);
    const QFileInfo jobInfo(jobPath);
    const QString rootCanonical = rootInfo.canonicalFilePath();
    const QString jobCanonical = jobInfo.canonicalFilePath();
    const QString parentCanonical = QFileInfo(jobInfo.absolutePath()).canonicalFilePath();
    if (rootCanonical.isEmpty() || jobCanonical.isEmpty() || !jobInfo.isDir()
        || jobInfo.isSymLink() || jobInfo.isJunction()
        || !samePath(rootCanonical, parentCanonical)
        || samePath(rootCanonical, jobCanonical)) {
        result.error = QStringLiteral(
            "Servo refused to delete a path that is not a verified world job directory.");
        return result;
    }

    std::error_code error;
#ifdef Q_OS_WIN
    std::filesystem::remove_all(std::filesystem::path(jobCanonical.toStdWString()), error);
#else
    std::filesystem::remove_all(std::filesystem::path(jobCanonical.toStdString()), error);
#endif
    if (error || QFileInfo::exists(jobCanonical)) {
        result.error = error
                           ? QStringLiteral("The world could not be deleted completely: %1")
                                 .arg(QString::fromStdString(error.message()))
                           : QStringLiteral("The world directory still exists after deletion.");
        return result;
    }
    result.success = true;
    return result;
}

QString WorldLibraryModel::formatBytes(qulonglong bytes)
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

QString WorldLibraryModel::formatCount(qint64 value)
{
    if (value <= 0)
        return QStringLiteral("Unknown");
    if (value >= 1000000)
        return QStringLiteral("%1 M").arg(value / 1000000.0, 0, 'f', 2);
    if (value >= 1000)
        return QStringLiteral("%1 K").arg(value / 1000.0, 0, 'f', 1);
    return QLocale().toString(value);
}

QString WorldLibraryModel::profileLabel(const QString &profile)
{
    if (profile == QStringLiteral("balanced-12gb"))
        return QStringLiteral("Balanced / 12 GB");
    if (profile == QStringLiteral("fidelity-12gb"))
        return QStringLiteral("Fidelity / 12 GB");
    if (profile == QStringLiteral("recovery-12gb"))
        return QStringLiteral("Recovery / 12 GB");
    return profile.isEmpty() ? QStringLiteral("Unknown") : profile;
}

QString WorldLibraryModel::qualityLabel(const QString &tier)
{
    if (tier == QStringLiteral("preferred"))
        return QStringLiteral("Preferred");
    if (tier == QStringLiteral("review-required"))
        return QStringLiteral("Review required");
    if (tier == QStringLiteral("production"))
        return QStringLiteral("Production");
    if (tier == QStringLiteral("usable"))
        return QStringLiteral("Usable");
    if (tier == QStringLiteral("experimental")
        || tier == QStringLiteral("degraded-experimental"))
        return QStringLiteral("Experimental");
    if (tier == QStringLiteral("failed"))
        return QStringLiteral("Failed");
    return QStringLiteral("Unrated");
}

QString WorldLibraryModel::qualityTone(const QString &tier)
{
    if (tier == QStringLiteral("preferred"))
        return QStringLiteral("success");
    if (tier == QStringLiteral("review-required"))
        return QStringLiteral("warning");
    if (tier == QStringLiteral("production"))
        return QStringLiteral("success");
    if (tier == QStringLiteral("usable"))
        return QStringLiteral("info");
    if (tier == QStringLiteral("experimental")
        || tier == QStringLiteral("degraded-experimental"))
        return QStringLiteral("warning");
    if (tier == QStringLiteral("failed"))
        return QStringLiteral("error");
    return QStringLiteral("neutral");
}

QString WorldLibraryModel::sanitizeDisplayName(const QString &value)
{
    QString result = value.simplified();
    result.remove(QChar::Null);
    if (result.size() > 80)
        result.truncate(80);
    return result;
}

void WorldLibraryModel::loadCatalog()
{
    QJsonObject root;
    if (!readJsonObject(m_catalogPath, &root)
        || root.value(QStringLiteral("schema")).toString()
               != QLatin1StringView(catalogSchema)) {
        return;
    }
    m_selectedWorldId = root.value(QStringLiteral("selectedWorldId")).toString();
    m_selectionPolicyVersion = root.value(QStringLiteral("selectionPolicyVersion")).toInt();
    const QJsonObject aliases = root.value(QStringLiteral("aliases")).toObject();
    for (auto iterator = aliases.constBegin(); iterator != aliases.constEnd(); ++iterator) {
        const QString alias = sanitizeDisplayName(iterator.value().toString());
        if (!alias.isEmpty())
            m_aliases.insert(iterator.key(), alias);
    }
}

bool WorldLibraryModel::saveCatalog()
{
    if (!QDir().mkpath(QFileInfo(m_catalogPath).absolutePath())) {
        setLastError(QStringLiteral("Unable to create the world library metadata directory."));
        return false;
    }
    QJsonObject aliases;
    for (auto iterator = m_aliases.constBegin(); iterator != m_aliases.constEnd(); ++iterator)
        aliases.insert(iterator.key(), iterator.value());
    const QJsonObject root {
        { QStringLiteral("schema"), QLatin1StringView(catalogSchema) },
        { QStringLiteral("selectionPolicyVersion"), m_selectionPolicyVersion },
        { QStringLiteral("selectedWorldId"), m_selectedWorldId },
        { QStringLiteral("aliases"), aliases },
    };
    QSaveFile file(m_catalogPath);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
        setLastError(QStringLiteral("Unable to save world library metadata: %1")
                         .arg(file.errorString()));
        return false;
    }
    const QByteArray payload = QJsonDocument(root).toJson(QJsonDocument::Indented);
    if (file.write(payload) != payload.size() || !file.commit()) {
        setLastError(QStringLiteral("Unable to commit world library metadata: %1")
                         .arg(file.errorString()));
        return false;
    }
    return true;
}

void WorldLibraryModel::rebuildVisibleRows()
{
    m_visibleRows.clear();
    const QString needle = m_filterText.trimmed();
    for (int row = 0; row < m_worlds.size(); ++row) {
        const WorldEntry &entry = m_worlds.at(row);
        if (!needle.isEmpty()) {
            const QString searchable = QStringLiteral("%1 %2 %3 %4 %5")
                                           .arg(entry.displayName,
                                                entry.sourceSummary,
                                                entry.profile,
                                                entry.qualityTier,
                                                entry.worldId);
            if (!searchable.contains(needle, Qt::CaseInsensitive))
                continue;
        }
        m_visibleRows.append(row);
    }
}

void WorldLibraryModel::sortWorlds()
{
    const QString mode = m_sortMode;
    std::sort(m_worlds.begin(),
              m_worlds.end(),
              [mode](const WorldEntry &left, const WorldEntry &right) {
                  if (mode == QStringLiteral("name")) {
                      const int comparison = QString::localeAwareCompare(left.displayName,
                                                                         right.displayName);
                      if (comparison != 0)
                          return comparison < 0;
                  } else if (mode == QStringLiteral("size")) {
                      if (left.sizeBytes != right.sizeBytes)
                          return left.sizeBytes > right.sizeBytes;
                  } else if (left.createdAt != right.createdAt) {
                      return left.createdAt > right.createdAt;
                  }
                  return left.worldId < right.worldId;
              });
}

void WorldLibraryModel::applyScannedWorlds(QVector<WorldEntry> worlds)
{
    const QString previousSelection = m_selectedWorldId;
    beginResetModel();
    m_worlds = std::move(worlds);
    sortWorlds();
    rebuildVisibleRows();
    endResetModel();

    QString nextSelection = previousSelection;
    if (m_selectionPolicyVersion < latestSelectionPolicyVersion) {
        // A visual-route publication is an explicit product choice made by
        // the world's validation gate. Prefer the strongest such route, while
        // keeping this selector independent of map names, job IDs, dates, and
        // route coordinates.
        const WorldEntry *bestQualified = nullptr;
        for (const WorldEntry &entry : std::as_const(m_worlds)) {
            if (!entry.published
                || entry.qualityTier != QLatin1String("hackathon-visual-route")
                || entry.routeTiles.isEmpty())
                continue;
            if (!bestQualified
                || entry.ssim > bestQualified->ssim
                || (qFuzzyCompare(entry.ssim, bestQualified->ssim)
                    && entry.psnr > bestQualified->psnr))
                bestQualified = &entry;
        }
        if (bestQualified)
            nextSelection = bestQualified->worldId;
        m_selectionPolicyVersion = latestSelectionPolicyVersion;
    }
    if (!m_pendingWorldPath.isEmpty()) {
        for (const WorldEntry &entry : std::as_const(m_worlds)) {
            if (samePath(entry.worldPath, m_pendingWorldPath)) {
                nextSelection = entry.worldId;
                break;
            }
        }
        m_pendingWorldPath.clear();
    }
    if (rowForId(nextSelection) < 0)
        nextSelection = m_worlds.isEmpty() ? QString() : m_worlds.first().worldId;
    m_selectedWorldId = nextSelection;
    saveCatalog();
    emit summaryChanged();
    emit selectionChanged();
}

int WorldLibraryModel::rowForId(const QString &worldId) const
{
    if (worldId.isEmpty())
        return -1;
    for (int row = 0; row < m_worlds.size(); ++row) {
        if (m_worlds.at(row).worldId == worldId)
            return row;
    }
    return -1;
}

int WorldLibraryModel::visibleRowForId(const QString &worldId) const
{
    if (worldId.isEmpty())
        return -1;
    for (int visibleRow = 0; visibleRow < m_visibleRows.size(); ++visibleRow) {
        if (m_worlds.at(m_visibleRows.at(visibleRow)).worldId == worldId)
            return visibleRow;
    }
    return -1;
}

QVariantMap WorldLibraryModel::entryMap(const WorldEntry &entry) const
{
    return {
        { QStringLiteral("worldId"), entry.worldId },
        { QStringLiteral("displayName"), entry.displayName },
        { QStringLiteral("originalName"), entry.originalName },
        { QStringLiteral("worldPath"), entry.worldPath },
        { QStringLiteral("plyPath"), entry.plyPath },
        { QStringLiteral("plyUrl"), QUrl::fromLocalFile(entry.plyPath) },
        { QStringLiteral("jobPath"), entry.jobPath },
        { QStringLiteral("previewUrl"), entry.previewUrl },
        { QStringLiteral("repairedReferenceUrl"), entry.repairedReferenceUrl },
        { QStringLiteral("sourceSummary"), entry.sourceSummary },
        { QStringLiteral("createdAt"), entry.createdAt.toUTC().toString(Qt::ISODateWithMs) },
        { QStringLiteral("createdText"), entry.createdText },
        { QStringLiteral("profile"), entry.profile },
        { QStringLiteral("profileLabel"), profileLabel(entry.profile) },
        { QStringLiteral("qualityTier"), entry.qualityTier },
        { QStringLiteral("qualityLabel"), qualityLabel(entry.qualityTier) },
        { QStringLiteral("qualityTone"), qualityTone(entry.qualityTier) },
        { QStringLiteral("psnr"), entry.psnr },
        { QStringLiteral("ssim"), entry.ssim },
        { QStringLiteral("gaussianCount"), entry.gaussianCount },
        { QStringLiteral("gaussianText"), formatCount(entry.gaussianCount) },
        { QStringLiteral("sizeBytes"), QVariant::fromValue(entry.sizeBytes) },
        { QStringLiteral("sizeText"), formatBytes(entry.sizeBytes) },
        { QStringLiteral("representation"), entry.representation },
        { QStringLiteral("pipelineRevision"), entry.pipelineRevision },
        { QStringLiteral("scaleText"), entry.scaleText },
        { QStringLiteral("published"), entry.published },
        { QStringLiteral("failureText"), entry.failureText },
        { QStringLiteral("recordedFrameUrls"), entry.recordedFrameUrls },
        { QStringLiteral("recordedFrameCount"), entry.recordedFrameUrls.size() },
        { QStringLiteral("routeTiles"), entry.routeTiles },
        { QStringLiteral("routeTileCount"), entry.routeTiles.size() },
    };
}

void WorldLibraryModel::setSelectedWorldId(const QString &worldId, bool persist)
{
    if (m_selectedWorldId == worldId)
        return;
    m_selectedWorldId = worldId;
    if (persist)
        saveCatalog();
    emit selectionChanged();
}

void WorldLibraryModel::setLastError(const QString &message)
{
    if (m_lastError == message)
        return;
    m_lastError = message;
    emit lastErrorChanged();
}

void WorldLibraryModel::setRefreshBusy(bool value)
{
    const bool wasBusy = busy();
    if (m_refreshBusy == value)
        return;
    m_refreshBusy = value;
    if (wasBusy != busy() || !m_deleteBusy)
        emit busyChanged();
}

void WorldLibraryModel::setDeleteBusy(bool value, const QString &worldName)
{
    const bool wasBusy = busy();
    const QString previousName = m_deletingWorldName;
    m_deleteBusy = value;
    m_deletingWorldName = value ? worldName : QString();
    if (wasBusy != busy() || previousName != m_deletingWorldName)
        emit busyChanged();
}
