#pragma once

#include <QJsonObject>
#include <QProcess>
#include <QStringList>
#include <QTimer>
#include <QVariantList>
#include <QtQmlIntegration>

class ReconstructionController final : public QObject
{
    Q_OBJECT
    QML_NAMED_ELEMENT(ReconstructionController)
    QML_SINGLETON

    Q_PROPERTY(QString state READ state NOTIFY stateChanged)
    Q_PROPERTY(QString stage READ stage NOTIFY stageChanged)
    Q_PROPERTY(QString message READ message NOTIFY messageChanged)
    Q_PROPERTY(QString details READ details NOTIFY detailsChanged)
    Q_PROPERTY(double progress READ progress NOTIFY progressChanged)
    Q_PROPERTY(QString progressText READ progressText NOTIFY progressChanged)
    Q_PROPERTY(bool ready READ ready NOTIFY readinessChanged)
    Q_PROPERTY(bool running READ running NOTIFY stateChanged)
    Q_PROPERTY(bool canCancel READ canCancel NOTIFY stateChanged)
    Q_PROPERTY(bool canRetry READ canRetry NOTIFY stateChanged)
    Q_PROPERTY(QVariantList dependencies READ dependencies NOTIFY dependenciesChanged)
    Q_PROPERTY(QString freeSpaceText READ freeSpaceText NOTIFY dependenciesChanged)
    Q_PROPERTY(QString runtimePath READ runtimePath CONSTANT)
    Q_PROPERTY(QString workerPath READ workerPath CONSTANT)
    Q_PROPERTY(QString pythonPath READ pythonPath CONSTANT)
    Q_PROPERTY(QString jobPath READ jobPath NOTIFY jobChanged)
    Q_PROPERTY(QString worldPath READ worldPath NOTIFY jobChanged)
    Q_PROPERTY(QString logPath READ logPath NOTIFY jobChanged)
    Q_PROPERTY(QString recentLog READ recentLog NOTIFY recentLogChanged)
    Q_PROPERTY(QStringList profileNames READ profileNames CONSTANT)
    Q_PROPERTY(QStringList profileLabels READ profileLabels CONSTANT)

public:
    explicit ReconstructionController(QObject *parent = nullptr);

    QString state() const;
    QString stage() const;
    QString message() const;
    QString details() const;
    double progress() const;
    QString progressText() const;
    bool ready() const;
    bool running() const;
    bool canCancel() const;
    bool canRetry() const;
    QVariantList dependencies() const;
    QString freeSpaceText() const;
    QString runtimePath() const;
    QString workerPath() const;
    QString pythonPath() const;
    QString jobPath() const;
    QString worldPath() const;
    QString logPath() const;
    QString recentLog() const;
    QStringList profileNames() const;
    QStringList profileLabels() const;

    Q_INVOKABLE void refreshPreflight();
    Q_INVOKABLE bool start(const QVariantList &sources,
                           const QString &profile,
                           const QString &worldName);
    Q_INVOKABLE void cancel();
    Q_INVOKABLE bool retry();
    Q_INVOKABLE void openJobFolder() const;
    Q_INVOKABLE void openWorldFolder() const;
    Q_INVOKABLE QString estimatedStorageText(qulonglong sourceBytes,
                                             const QString &profile) const;
    Q_INVOKABLE double expectedVramGiB(const QString &profile) const;
    Q_INVOKABLE bool capacityReady(qulonglong sourceBytes,
                                   const QString &profile) const;
    Q_INVOKABLE QString capacityIssue(qulonglong sourceBytes,
                                      const QString &profile) const;

signals:
    void stateChanged();
    void stageChanged();
    void messageChanged();
    void detailsChanged();
    void progressChanged();
    void readinessChanged();
    void dependenciesChanged();
    void jobChanged();
    void recentLogChanged();
    void worldPublished(const QString &worldPath);

private:
    friend class ReconstructionControllerTests;

    enum class ProcessMode { None, Preflight, Job };

    bool launch(ProcessMode mode, const QStringList &arguments);
    bool launchDetachedJob(const QStringList &arguments);
    void readProcessOutput();
    void pollDetachedJob();
    void processLine(const QByteArray &line);
    void protocolFailure(const QString &message);
    void handleEvent(const QJsonObject &event);
    void handleChildEvent(const QJsonObject &event);
    void processFinished(int exitCode, QProcess::ExitStatus exitStatus);
    bool writeJob(const QVariantList &sources,
                  const QString &profile,
                  const QString &worldName);
    void beginPublishedWorldValidation(const QString &path);
    static bool validatePublishedWorld(const QString &path,
                                       const QString &jobPath,
                                       const QString &expectedJobId,
                                       const QString &pipelineRevision,
                                       QString *error);
    void refreshPreflightAfterJob();
    bool restoreActiveJob();
    bool persistActiveJob() const;
    void clearActiveJob() const;
    void setState(const QString &value);
    void setStage(const QString &value);
    void setMessage(const QString &value);
    void setDetails(const QString &value);
    void setProgress(double value, const QString &text = {});
    void appendRecentLog(const QString &line);
    static QString locatePython();
    static QString locateWorker();
    static QString stageLabel(const QString &stage);
    static QString formatCount(qint64 value);
    static QString sanitizeWorldName(const QString &value);
    static bool processAlive(qint64 processId, const QString &identity = {});
    static QString processIdentity(qint64 processId);

    QProcess m_process;
    QTimer m_jobPollTimer;
    ProcessMode m_mode = ProcessMode::None;
    QByteArray m_outputBuffer;
    QByteArray m_eventBuffer;
    QString m_state = QStringLiteral("checking");
    QString m_stage;
    QString m_message = QStringLiteral("Checking native reconstruction runtime");
    QString m_details;
    double m_progress = -1.0;
    QString m_progressText;
    bool m_preflightReady = false;
    bool m_jobActive = false;
    bool m_terminalEventSeen = false;
    bool m_protocolInvalid = false;
    bool m_artifactValidationActive = false;
    bool m_preflightRefreshPending = false;
    qint64 m_detachedProcessId = 0;
    qint64 m_jobLaunchMilliseconds = 0;
    qint64 m_eventOffset = 0;
    qint64 m_lastEventSequence = 0;
    qulonglong m_freeBytes = 0;
    qulonglong m_gpuFreeBytes = 0;
    qulonglong m_gpuTotalBytes = 0;
    QVariantList m_dependencies;
    QString m_freeSpaceText;
    QString m_runtimePath;
    QString m_workerPath;
    QString m_pythonPath;
    QString m_jobPath;
    QString m_worldPath;
    QString m_logPath;
    QString m_expectedJobId;
    QString m_pipelineRevision;
    QString m_processIdentity;
    QString m_postPreflightState;
    QString m_postPreflightMessage;
    QString m_postPreflightDetails;
    QString m_postPreflightProgressText;
    double m_postPreflightProgress = -1.0;
    QStringList m_recentLines;
};
