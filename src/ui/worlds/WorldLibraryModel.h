#pragma once

#include <QAbstractListModel>
#include <QDateTime>
#include <QHash>
#include <QString>
#include <QUrl>
#include <QVariantMap>
#include <QtQmlIntegration>

class WorldLibraryModel final : public QAbstractListModel
{
    Q_OBJECT
    QML_NAMED_ELEMENT(WorldLibraryModel)
    QML_SINGLETON

    Q_PROPERTY(int count READ count NOTIFY summaryChanged)
    Q_PROPERTY(int totalCount READ totalCount NOTIFY summaryChanged)
    Q_PROPERTY(qulonglong totalBytes READ totalBytes NOTIFY summaryChanged)
    Q_PROPERTY(QString totalBytesText READ totalBytesText NOTIFY summaryChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString busyText READ busyText NOTIFY busyChanged)
    Q_PROPERTY(QString filterText READ filterText WRITE setFilterText NOTIFY filterTextChanged)
    Q_PROPERTY(QString sortMode READ sortMode WRITE setSortMode NOTIFY sortModeChanged)
    Q_PROPERTY(QString selectedWorldId READ selectedWorldId NOTIFY selectionChanged)
    Q_PROPERTY(int selectedIndex READ selectedIndex NOTIFY selectionChanged)
    Q_PROPERTY(bool hasSelection READ hasSelection NOTIFY selectionChanged)
    Q_PROPERTY(QVariantMap selectedWorld READ selectedWorld NOTIFY selectionChanged)
    Q_PROPERTY(QString jobsRoot READ jobsRoot CONSTANT)
    Q_PROPERTY(QString lastError READ lastError NOTIFY lastErrorChanged)

public:
    enum Role {
        WorldIdRole = Qt::UserRole + 1,
        DisplayNameRole,
        OriginalNameRole,
        WorldPathRole,
        PlyPathRole,
        JobPathRole,
        PreviewUrlRole,
        SourceSummaryRole,
        CreatedAtRole,
        CreatedTextRole,
        ProfileRole,
        ProfileLabelRole,
        QualityTierRole,
        QualityLabelRole,
        QualityToneRole,
        PsnrRole,
        SsimRole,
        GaussianCountRole,
        GaussianTextRole,
        SizeBytesRole,
        SizeTextRole,
        RepresentationRole,
        PipelineRevisionRole,
        ScaleTextRole,
        PublishedRole,
        FailureTextRole,
        RecordedFrameUrlsRole,
        RecordedFrameCountRole
    };
    Q_ENUM(Role)

    explicit WorldLibraryModel(QObject *parent = nullptr);
    WorldLibraryModel(const QString &jobsRoot,
                      const QString &catalogPath,
                      QObject *parent = nullptr);
    ~WorldLibraryModel() override;

    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    int count() const;
    int totalCount() const;
    qulonglong totalBytes() const;
    QString totalBytesText() const;
    bool busy() const;
    QString busyText() const;
    QString filterText() const;
    void setFilterText(const QString &value);
    QString sortMode() const;
    void setSortMode(const QString &value);
    QString selectedWorldId() const;
    int selectedIndex() const;
    bool hasSelection() const;
    QVariantMap selectedWorld() const;
    QString jobsRoot() const;
    QString lastError() const;

    Q_INVOKABLE void refresh();
    Q_INVOKABLE bool selectWorld(const QString &worldId);
    Q_INVOKABLE bool selectWorldMatching(const QString &query);
    Q_INVOKABLE void selectWorldPath(const QString &worldPath);
    Q_INVOKABLE bool renameWorld(const QString &worldId, const QString &displayName);
    Q_INVOKABLE bool deleteWorld(const QString &worldId);
    Q_INVOKABLE void openWorldFolder(const QString &worldId);
    Q_INVOKABLE void openJobFolder(const QString &worldId);
    Q_INVOKABLE void clearLastError();

signals:
    void summaryChanged();
    void busyChanged();
    void filterTextChanged();
    void sortModeChanged();
    void selectionChanged();
    void lastErrorChanged();
    void worldDeleted(const QString &worldId,
                      const QString &displayName,
                      qulonglong recoveredBytes);

private:
    struct WorldEntry;
    struct DeleteResult;

    static QString defaultJobsRoot();
    static QString defaultCatalogPath();
    static QVector<WorldEntry> scanJobs(const QString &jobsRoot,
                                        const QHash<QString, QString> &aliases);
    static DeleteResult deleteJobTree(const QString &jobsRoot,
                                      const QString &jobPath);
    static QString formatBytes(qulonglong bytes);
    static QString formatCount(qint64 value);
    static QString profileLabel(const QString &profile);
    static QString qualityLabel(const QString &tier);
    static QString qualityTone(const QString &tier);
    static QString sanitizeDisplayName(const QString &value);

    void loadCatalog();
    bool saveCatalog();
    void rebuildVisibleRows();
    void sortWorlds();
    void applyScannedWorlds(QVector<WorldEntry> worlds);
    int rowForId(const QString &worldId) const;
    int visibleRowForId(const QString &worldId) const;
    QVariantMap entryMap(const WorldEntry &entry) const;
    void setSelectedWorldId(const QString &worldId, bool persist = true);
    void setLastError(const QString &message);
    void setRefreshBusy(bool value);
    void setDeleteBusy(bool value, const QString &worldName = {});

    QVector<WorldEntry> m_worlds;
    QVector<int> m_visibleRows;
    QHash<QString, QString> m_aliases;
    QString m_jobsRoot;
    QString m_catalogPath;
    QString m_filterText;
    QString m_sortMode = QStringLiteral("newest");
    QString m_selectedWorldId;
    QString m_pendingWorldPath;
    QString m_lastError;
    QString m_deletingWorldName;
    int m_selectionPolicyVersion = 0;
    bool m_refreshBusy = false;
    bool m_deleteBusy = false;
    bool m_refreshPending = false;
};
