#pragma once

#include <QAbstractListModel>
#include <QSet>
#include <QThreadPool>
#include <QTimer>
#include <QUrl>
#include <QtQmlIntegration>

class MediaSourceModel final : public QAbstractListModel
{
    Q_OBJECT
    QML_NAMED_ELEMENT(MediaSourceModel)
    QML_SINGLETON

    Q_PROPERTY(int count READ count NOTIFY summaryChanged)
    Q_PROPERTY(int readyCount READ readyCount NOTIFY summaryChanged)
    Q_PROPERTY(int errorCount READ errorCount NOTIFY summaryChanged)
    Q_PROPERTY(int busyCount READ busyCount NOTIFY summaryChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY summaryChanged)
    Q_PROPERTY(quint64 totalBytes READ totalBytes NOTIFY summaryChanged)
    Q_PROPERTY(QString totalBytesText READ totalBytesText NOTIFY summaryChanged)
    Q_PROPERTY(quint64 readyBytes READ readyBytes NOTIFY summaryChanged)
    Q_PROPERTY(QString readyBytesText READ readyBytesText NOTIFY summaryChanged)
    Q_PROPERTY(bool ffprobeAvailable READ ffprobeAvailable NOTIFY ffprobeChanged)
    Q_PROPERTY(QString ffprobePath READ ffprobePath NOTIFY ffprobeChanged)
    Q_PROPERTY(QString catalogPath READ catalogPath CONSTANT)
    Q_PROPERTY(QString activityText READ activityText NOTIFY activityChanged)
    Q_PROPERTY(QString lastError READ lastError NOTIFY lastErrorChanged)

public:
    enum Role {
        AssetIdRole = Qt::UserRole + 1,
        SourceUrlRole,
        PathRole,
        NameRole,
        KindRole,
        StatusRole,
        StatusTextRole,
        SizeBytesRole,
        SizeTextRole,
        DimensionsRole,
        DurationSecondsRole,
        DurationTextRole,
        FramesPerSecondRole,
        FramesPerSecondTextRole,
        FrameCountRole,
        CodecRole,
        ContainerRole,
        PixelFormatRole,
        ColorDescriptionRole,
        RotationRole,
        FingerprintRole,
        ErrorTextRole
    };
    Q_ENUM(Role)

    explicit MediaSourceModel(QObject *parent = nullptr);
    ~MediaSourceModel() override;

    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    int count() const;
    int readyCount() const;
    int errorCount() const;
    int busyCount() const;
    bool busy() const;
    quint64 totalBytes() const;
    QString totalBytesText() const;
    quint64 readyBytes() const;
    QString readyBytesText() const;
    bool ffprobeAvailable() const;
    QString ffprobePath() const;
    QString catalogPath() const;
    QString activityText() const;
    QString lastError() const;

    Q_INVOKABLE void addUrls(const QVariantList &urls);
    Q_INVOKABLE void addUrl(const QUrl &url);
    Q_INVOKABLE void retry(int row);
    Q_INVOKABLE void removeReference(int row);
    Q_INVOKABLE void clearLastError();
    Q_INVOKABLE QVariantList readySources() const;

signals:
    void summaryChanged();
    void activityChanged();
    void lastErrorChanged();
    void ffprobeChanged();

private:
    struct Asset {
        QString id;
        QUrl sourceUrl;
        QString path;
        QString name;
        QString kind = QStringLiteral("media");
        QString status = QStringLiteral("queued");
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

    struct ProbeResult;

    void loadCatalog();
    void scheduleSave();
    void saveCatalog();
    void enqueuePath(const QString &path);
    void enqueueFile(const QString &path);
    void scanFolder(const QString &path);
    void scheduleProbe(const QString &assetId);
    void refreshFfprobe();
    int rowForId(const QString &assetId) const;
    int rowForPath(const QString &path) const;
    void applyProbeResult(const QString &assetId, const ProbeResult &result);
    void updateActivity();
    void setLastError(const QString &message);
    bool isFolderCandidate(const QString &path) const;
    static QString normalizedPath(const QString &path);
    static QString formatBytes(quint64 bytes);
    static QString formatDuration(double seconds);
    static QString formatFramesPerSecond(double framesPerSecond);
    static ProbeResult probeFile(const QString &path,
                                 const QString &ffprobeExecutable,
                                 const QSet<QString> &imageExtensions);

    QVector<Asset> m_assets;
    QThreadPool m_probePool;
    QThreadPool m_scanPool;
    QTimer m_saveTimer;
    QSet<QString> m_imageExtensions;
    QSet<QString> m_folderExtensions;
    QString m_ffprobePath;
    QString m_catalogPath;
    QString m_activityText;
    QString m_lastError;
    int m_activeFolderScans = 0;
};
