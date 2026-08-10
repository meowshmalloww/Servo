#include "ReconstructionController.h"

#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDateTime>
#include <QDesktopServices>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLocale>
#include <QRegularExpression>
#include <QSaveFile>
#include <QStandardPaths>
#include <QStorageInfo>
#include <QTimer>
#include <QUrl>
#include <QUuid>
#include <QtConcurrentRun>

#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>

#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <cerrno>
#include <csignal>
#endif

namespace {
constexpr auto jobSchema = "servo.reconstruction-job/v1";
constexpr auto eventSchema = "servo.reconstruction-event/v1";
constexpr auto worldSchema = "servo.gaussian-world/v1";
constexpr auto supportedWorkerVersion = "0.3.0";
constexpr qulonglong gibibyte = 1024ULL * 1024ULL * 1024ULL;

struct ProfilePresentation {
    const char *name;
    const char *label;
    double vramGiB;
    double diskMultiplier;
};

constexpr ProfilePresentation profiles[] = {
    { "balanced-12gb", "Servo Balanced / 12 GB", 10.5, 5.0 },
    { "fidelity-12gb", "Servo Fidelity / 12 GB", 11.0, 7.0 },
    { "recovery-12gb", "Recovery / difficult capture", 8.0, 5.5 },
};

const ProfilePresentation *profileForName(const QString &name)
{
    for (const ProfilePresentation &profile : profiles) {
        if (name == QLatin1StringView(profile.name))
            return &profile;
    }
    return nullptr;
}

QString formatBytes(qulonglong bytes)
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
} // namespace

ReconstructionController::ReconstructionController(QObject *parent)
    : QObject(parent)
    , m_runtimePath(QDir(QStandardPaths::writableLocation(
                            QStandardPaths::AppLocalDataLocation))
                        .filePath(QStringLiteral("reconstruction")))
    , m_workerPath(locateWorker())
    , m_pythonPath(locatePython())
{
    m_process.setProcessChannelMode(QProcess::MergedChannels);
    connect(&m_process,
            &QProcess::readyReadStandardOutput,
            this,
            &ReconstructionController::readProcessOutput);
    connect(&m_process,
            qOverload<int, QProcess::ExitStatus>(&QProcess::finished),
            this,
            &ReconstructionController::processFinished);
    connect(&m_process,
            &QProcess::errorOccurred,
            this,
            [this](QProcess::ProcessError error) {
                if (error == QProcess::FailedToStart) {
                    const ProcessMode failedMode = m_mode;
                    m_mode = ProcessMode::None;
                    setState(QStringLiteral("blocked"));
                    setMessage(QStringLiteral("Unable to start the reconstruction worker"));
                    setDetails(m_process.errorString());
                    if (failedMode == ProcessMode::Preflight)
                        m_preflightReady = false;
                    emit readinessChanged();
                }
            });
    connect(&m_process,
            &QProcess::stateChanged,
            this,
            [this](QProcess::ProcessState) {
                emit stateChanged();
                emit readinessChanged();
            });
    m_jobPollTimer.setInterval(250);
    connect(&m_jobPollTimer,
            &QTimer::timeout,
            this,
            &ReconstructionController::pollDetachedJob);

    if (!restoreActiveJob())
        QTimer::singleShot(0, this, &ReconstructionController::refreshPreflight);
}

QString ReconstructionController::state() const { return m_state; }
QString ReconstructionController::stage() const { return m_stage; }
QString ReconstructionController::message() const { return m_message; }
QString ReconstructionController::details() const { return m_details; }
double ReconstructionController::progress() const { return m_progress; }
QString ReconstructionController::progressText() const { return m_progressText; }
bool ReconstructionController::ready() const
{
    return m_preflightReady && !m_jobActive && !m_artifactValidationActive
           && m_process.state() == QProcess::NotRunning
           && m_mode == ProcessMode::None;
}
bool ReconstructionController::running() const
{
    return m_jobActive || m_artifactValidationActive
           || m_process.state() != QProcess::NotRunning
           || m_state == QStringLiteral("running")
           || m_state == QStringLiteral("cancelling")
           || m_state == QStringLiteral("checking");
}
bool ReconstructionController::canCancel() const
{
    return m_jobActive && m_state == QStringLiteral("running");
}
bool ReconstructionController::canRetry() const
{
    return m_preflightReady && !m_jobActive
           && m_process.state() == QProcess::NotRunning && !m_jobPath.isEmpty()
           && (m_state == QStringLiteral("failed")
               || m_state == QStringLiteral("cancelled"));
}
QVariantList ReconstructionController::dependencies() const { return m_dependencies; }
QString ReconstructionController::freeSpaceText() const { return m_freeSpaceText; }
QString ReconstructionController::runtimePath() const { return m_runtimePath; }
QString ReconstructionController::workerPath() const { return m_workerPath; }
QString ReconstructionController::pythonPath() const { return m_pythonPath; }
QString ReconstructionController::jobPath() const { return m_jobPath; }
QString ReconstructionController::worldPath() const { return m_worldPath; }
QString ReconstructionController::logPath() const { return m_logPath; }
QString ReconstructionController::recentLog() const { return m_recentLines.join(QLatin1Char('\n')); }

QStringList ReconstructionController::profileNames() const
{
    QStringList result;
    for (const ProfilePresentation &profile : profiles)
        result.append(QLatin1StringView(profile.name));
    return result;
}

QStringList ReconstructionController::profileLabels() const
{
    QStringList result;
    for (const ProfilePresentation &profile : profiles)
        result.append(QLatin1StringView(profile.label));
    return result;
}

void ReconstructionController::refreshPreflight()
{
    if (m_jobActive || m_artifactValidationActive
        || m_process.state() != QProcess::NotRunning)
        return;
    setState(QStringLiteral("checking"));
    setStage({});
    setMessage(QStringLiteral("Verifying native CUDA reconstruction runtime"));
    setDetails({});
    setProgress(-1.0);
    m_preflightReady = false;
    emit readinessChanged();
    if (m_pythonPath.isEmpty() || m_workerPath.isEmpty()) {
        setState(QStringLiteral("blocked"));
        setMessage(QStringLiteral("Native reconstruction worker is not installed"));
        setDetails(m_pythonPath.isEmpty()
                       ? QStringLiteral("Python 3.11 worker environment was not found.")
                       : QStringLiteral("servo_worker.py was not found."));
        return;
    }
    if (!launch(ProcessMode::Preflight,
                { m_workerPath,
                  QStringLiteral("preflight"),
                  QStringLiteral("--verify-kernel") })) {
        setState(QStringLiteral("blocked"));
        setMessage(QStringLiteral("Unable to launch native preflight"));
    }
}

bool ReconstructionController::start(const QVariantList &sources,
                                     const QString &profile,
                                     const QString &worldName)
{
    if (!ready() || sources.isEmpty() || profileForName(profile) == nullptr)
        return false;
    qulonglong sourceBytes = 0;
    for (const QVariant &value : sources)
        sourceBytes += value.toMap().value(QStringLiteral("sizeBytes")).toULongLong();
    if (!capacityReady(sourceBytes, profile)) {
        setMessage(QStringLiteral("Local capacity gate did not pass"));
        setDetails(capacityIssue(sourceBytes, profile));
        return false;
    }
    if (!writeJob(sources, profile, worldName))
        return false;
    setState(QStringLiteral("running"));
    setStage(QStringLiteral("queued"));
    setMessage(QStringLiteral("Starting reconstruction worker"));
    setDetails({});
    setProgress(-1.0, QStringLiteral("Queued"));
    if (!launchDetachedJob({ m_workerPath,
                             QStringLiteral("run"),
                             QStringLiteral("--job"),
                             m_jobPath })) {
        setState(QStringLiteral("failed"));
        setMessage(QStringLiteral("Unable to start the detached reconstruction worker"));
        return false;
    }
    return true;
}

void ReconstructionController::cancel()
{
    if (!canCancel() || m_jobPath.isEmpty())
        return;
    QSaveFile request(QDir(QFileInfo(m_jobPath).absolutePath())
                          .filePath(QStringLiteral("cancel.request")));
    if (!request.open(QIODevice::WriteOnly | QIODevice::Text)) {
        setMessage(QStringLiteral("Could not request cancellation"));
        setDetails(request.errorString());
        return;
    }
    request.write(QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs).toUtf8());
    request.write("\n");
    if (!request.commit()) {
        setMessage(QStringLiteral("Could not commit the cancellation request"));
        setDetails(request.errorString());
        return;
    }
    setState(QStringLiteral("cancelling"));
    setMessage(QStringLiteral("Cancelling after a safe checkpoint"));
}

bool ReconstructionController::retry()
{
    if (!canRetry())
        return false;
    const QString cancelPath = QDir(QFileInfo(m_jobPath).absolutePath())
                                   .filePath(QStringLiteral("cancel.request"));
    if (QFileInfo::exists(cancelPath) && !QFile::remove(cancelPath)) {
        setMessage(QStringLiteral("Unable to clear the previous cancellation request"));
        setDetails(cancelPath);
        return false;
    }
    setState(QStringLiteral("running"));
    setStage(QStringLiteral("resume"));
    setMessage(QStringLiteral("Validating receipts and resuming"));
    setDetails({});
    setProgress(-1.0, QStringLiteral("Resuming"));
    if (!launchDetachedJob({ m_workerPath,
                             QStringLiteral("run"),
                             QStringLiteral("--job"),
                             m_jobPath })) {
        setState(QStringLiteral("failed"));
        setMessage(QStringLiteral("Unable to restart the detached reconstruction worker"));
        return false;
    }
    return true;
}

void ReconstructionController::openJobFolder() const
{
    if (!m_jobPath.isEmpty())
        QDesktopServices::openUrl(QUrl::fromLocalFile(QFileInfo(m_jobPath).absolutePath()));
}

void ReconstructionController::openWorldFolder() const
{
    if (!m_worldPath.isEmpty())
        QDesktopServices::openUrl(QUrl::fromLocalFile(m_worldPath));
}

QString ReconstructionController::estimatedStorageText(qulonglong sourceBytes,
                                                       const QString &profile) const
{
    const ProfilePresentation *presentation = profileForName(profile);
    if (!presentation)
        return QStringLiteral("Unknown");
    const long double estimate = std::max<long double>(
        4.0L * 1024 * 1024 * 1024,
        static_cast<long double>(sourceBytes) * presentation->diskMultiplier);
    const qulonglong bounded = estimate > std::numeric_limits<qulonglong>::max()
                                   ? std::numeric_limits<qulonglong>::max()
                                   : static_cast<qulonglong>(estimate);
    return QStringLiteral("~%1 derived").arg(formatBytes(bounded));
}

double ReconstructionController::expectedVramGiB(const QString &profile) const
{
    const ProfilePresentation *presentation = profileForName(profile);
    return presentation ? presentation->vramGiB : 0.0;
}

bool ReconstructionController::capacityReady(qulonglong sourceBytes,
                                             const QString &profile) const
{
    const ProfilePresentation *presentation = profileForName(profile);
    if (!presentation)
        return false;
    const long double derived = std::max<long double>(
        4.0L * gibibyte,
        static_cast<long double>(sourceBytes) * presentation->diskMultiplier);
    const long double requiredDisk = derived + 2.0L * gibibyte;
    const long double requiredVram = presentation->vramGiB * gibibyte;
    const QStorageInfo storage(m_runtimePath);
    const qulonglong currentFreeBytes = storage.isValid() && storage.isReady()
                                               ? storage.bytesAvailable()
                                               : m_freeBytes;
    return static_cast<long double>(currentFreeBytes) >= requiredDisk
           && static_cast<long double>(m_gpuTotalBytes) >= requiredVram
           && static_cast<long double>(m_gpuFreeBytes) >= requiredVram;
}

QString ReconstructionController::capacityIssue(qulonglong sourceBytes,
                                                const QString &profile) const
{
    const ProfilePresentation *presentation = profileForName(profile);
    if (!presentation)
        return QStringLiteral("Unknown reconstruction profile.");
    const long double derived = std::max<long double>(
        4.0L * gibibyte,
        static_cast<long double>(sourceBytes) * presentation->diskMultiplier);
    const qulonglong requiredDisk = static_cast<qulonglong>(derived + 2.0L * gibibyte);
    const qulonglong requiredVram = static_cast<qulonglong>(
        std::ceil(presentation->vramGiB * gibibyte));
    const QStorageInfo storage(m_runtimePath);
    const qulonglong currentFreeBytes = storage.isValid() && storage.isReady()
                                               ? storage.bytesAvailable()
                                               : m_freeBytes;
    if (currentFreeBytes < requiredDisk) {
        return QStringLiteral("%1 free workspace is required; %2 is available.")
            .arg(formatBytes(requiredDisk), formatBytes(currentFreeBytes));
    }
    if (m_gpuTotalBytes < requiredVram) {
        return QStringLiteral("This profile requires %1 VRAM; the GPU exposes %2.")
            .arg(formatBytes(requiredVram), formatBytes(m_gpuTotalBytes));
    }
    if (m_gpuFreeBytes < requiredVram) {
        return QStringLiteral("Close other GPU workloads: %1 free VRAM is required; %2 is currently free.")
            .arg(formatBytes(requiredVram), formatBytes(m_gpuFreeBytes));
    }
    return {};
}

bool ReconstructionController::launch(ProcessMode mode,
                                      const QStringList &arguments)
{
    if (m_jobActive || m_mode != ProcessMode::None
        || m_process.state() != QProcess::NotRunning) {
        setDetails(QStringLiteral("A reconstruction process is already active."));
        return false;
    }
    m_mode = mode;
    m_outputBuffer.clear();
    m_lastEventSequence = 0;
    m_terminalEventSeen = false;
    m_protocolInvalid = false;
    m_process.setProgram(m_pythonPath);
    m_process.setArguments(arguments);
    m_process.start(QIODevice::ReadOnly);
    return true;
}

bool ReconstructionController::launchDetachedJob(const QStringList &arguments)
{
    if (m_jobActive || m_mode != ProcessMode::None
        || m_process.state() != QProcess::NotRunning || m_logPath.isEmpty()) {
        setDetails(QStringLiteral("A reconstruction process is already active."));
        return false;
    }
    m_mode = ProcessMode::Job;
    m_eventBuffer.clear();
    m_eventOffset = QFileInfo(m_logPath).exists() ? QFileInfo(m_logPath).size() : 0;
    m_lastEventSequence = 0;
    m_terminalEventSeen = false;
    m_protocolInvalid = false;
    m_detachedProcessId = 0;
    m_processIdentity.clear();
    m_jobLaunchMilliseconds = QDateTime::currentMSecsSinceEpoch();
    if (!persistActiveJob()) {
        m_mode = ProcessMode::None;
        setDetails(QStringLiteral("Unable to commit the active-job recovery record."));
        return false;
    }

    QProcess detached;
    detached.setProgram(m_pythonPath);
    detached.setArguments(arguments);
    detached.setWorkingDirectory(QFileInfo(m_jobPath).absolutePath());
    detached.setStandardOutputFile(QProcess::nullDevice());
    detached.setStandardErrorFile(
        QDir(QFileInfo(m_jobPath).absolutePath())
            .filePath(QStringLiteral("worker-stderr.log")),
        QIODevice::Append);
    qint64 processId = 0;
    if (!detached.startDetached(&processId) || processId <= 0) {
        m_mode = ProcessMode::None;
        clearActiveJob();
        setDetails(detached.errorString());
        return false;
    }
    m_detachedProcessId = processId;
    m_jobActive = true;
    if (!persistActiveJob())
        appendRecentLog(QStringLiteral("The worker started, but its PID could not be added to the recovery record."));
    m_jobPollTimer.start();
    emit stateChanged();
    emit readinessChanged();
    return true;
}

void ReconstructionController::readProcessOutput()
{
    m_outputBuffer += m_process.readAllStandardOutput();
    qsizetype newline = -1;
    while ((newline = m_outputBuffer.indexOf('\n')) >= 0) {
        const QByteArray line = m_outputBuffer.left(newline).trimmed();
        m_outputBuffer.remove(0, newline + 1);
        if (!line.isEmpty())
            processLine(line);
    }
}

void ReconstructionController::pollDetachedJob()
{
    QFile events(m_logPath);
    if (events.open(QIODevice::ReadOnly)) {
        if (events.size() < m_eventOffset) {
            m_eventOffset = 0;
            m_eventBuffer.clear();
            m_lastEventSequence = 0;
        }
        if (events.seek(m_eventOffset)) {
            m_eventBuffer += events.readAll();
            m_eventOffset = events.pos();
            qsizetype newline = -1;
            while ((newline = m_eventBuffer.indexOf('\n')) >= 0) {
                const QByteArray line = m_eventBuffer.left(newline).trimmed();
                m_eventBuffer.remove(0, newline + 1);
                if (!line.isEmpty())
                    processLine(line);
            }
        }
    }

    const bool launchGraceElapsed =
        QDateTime::currentMSecsSinceEpoch() - m_jobLaunchMilliseconds >= 5000;
    if (m_jobActive && launchGraceElapsed
        && !processAlive(m_detachedProcessId, m_processIdentity)) {
        if (!m_terminalEventSeen && m_state != QStringLiteral("failed")) {
            setState(QStringLiteral("failed"));
            setMessage(QStringLiteral("Reconstruction worker exited without a terminal event"));
            setDetails(QStringLiteral("Inspect worker-stderr.log and events.jsonl in the job folder."));
            setProgress(-1.0, QStringLiteral("Failed"));
        }
        m_jobActive = false;
        m_mode = ProcessMode::None;
        m_detachedProcessId = 0;
        m_processIdentity.clear();
        m_jobPollTimer.stop();
        clearActiveJob();
        emit stateChanged();
        emit readinessChanged();
        if (m_artifactValidationActive)
            m_preflightRefreshPending = true;
        else
            refreshPreflightAfterJob();
    }
}

void ReconstructionController::processLine(const QByteArray &line)
{
    if (m_protocolInvalid)
        return;
    QJsonParseError error;
    const QJsonDocument document = QJsonDocument::fromJson(line, &error);
    if (error.error != QJsonParseError::NoError || !document.isObject()) {
        if (m_mode == ProcessMode::Job)
            protocolFailure(QStringLiteral("The job event log contains malformed JSON."));
        else
            appendRecentLog(QString::fromUtf8(line));
        return;
    }
    const QJsonObject event = document.object();
    const QString type = event.value(QStringLiteral("event")).toString();
    const qint64 sequence = event.value(QStringLiteral("sequence")).toInteger(-1);
    if (event.value(QStringLiteral("schema")).toString()
            != QLatin1StringView(eventSchema)
        || event.value(QStringLiteral("workerVersion")).toString()
               != QLatin1StringView(supportedWorkerVersion)
        || type.isEmpty() || sequence <= 0) {
        protocolFailure(QStringLiteral("The reconstruction worker emitted an unsupported event contract."));
        return;
    }
    if (m_mode == ProcessMode::Job) {
        if (event.value(QStringLiteral("jobId")).toString() != m_expectedJobId) {
            protocolFailure(QStringLiteral("A reconstruction event belongs to a different job."));
            return;
        }
        if (sequence <= m_lastEventSequence) {
            if (type == QStringLiteral("job_opened") && sequence == 1)
                m_lastEventSequence = 0;
            else {
                protocolFailure(QStringLiteral("The reconstruction event sequence moved backward."));
                return;
            }
        }
    } else if (sequence <= m_lastEventSequence) {
        protocolFailure(QStringLiteral("The preflight event sequence moved backward."));
        return;
    }
    m_lastEventSequence = sequence;
    handleEvent(event);
}

void ReconstructionController::protocolFailure(const QString &message)
{
    if (m_protocolInvalid)
        return;
    m_protocolInvalid = true;
    setState(m_mode == ProcessMode::Preflight ? QStringLiteral("blocked")
                                              : QStringLiteral("failed"));
    setMessage(QStringLiteral("Unsupported reconstruction worker protocol"));
    setDetails(message);
    if (m_mode == ProcessMode::Preflight) {
        m_preflightReady = false;
        emit readinessChanged();
    }
}

void ReconstructionController::handleEvent(const QJsonObject &event)
{
    const QString type = event.value(QStringLiteral("event")).toString();
    if (type == QStringLiteral("preflight_result")) {
        m_dependencies = event.value(QStringLiteral("dependencies")).toArray().toVariantList();
        m_freeSpaceText = event.value(QStringLiteral("freeText")).toString();
        m_freeBytes = static_cast<qulonglong>(
            std::max<qint64>(0, event.value(QStringLiteral("freeBytes")).toInteger()));
        m_gpuFreeBytes = static_cast<qulonglong>(
            std::max<qint64>(0, event.value(QStringLiteral("gpuFreeBytes")).toInteger()));
        m_gpuTotalBytes = static_cast<qulonglong>(
            std::max<qint64>(0, event.value(QStringLiteral("gpuTotalBytes")).toInteger()));
        m_pipelineRevision = event.value(QStringLiteral("pipelineRevision")).toString();
        m_preflightReady = event.value(QStringLiteral("ready")).toBool();
        if (m_pipelineRevision.isEmpty())
            m_preflightReady = false;
        emit dependenciesChanged();
        emit readinessChanged();
        setState(m_preflightReady ? QStringLiteral("ready")
                                  : QStringLiteral("blocked"));
        setMessage(m_preflightReady
                       ? QStringLiteral("Native reconstruction runtime is ready")
                       : QStringLiteral("Reconstruction dependencies need attention"));
        if (!m_preflightReady) {
            QStringList missing;
            for (const QVariant &value : std::as_const(m_dependencies)) {
                const QVariantMap item = value.toMap();
                if (!item.value(QStringLiteral("ready")).toBool())
                    missing.append(item.value(QStringLiteral("name")).toString());
            }
            setDetails(QStringLiteral("Missing or mismatched: %1").arg(missing.join(QStringLiteral(", "))));
        }
        if (m_preflightReady && !m_postPreflightState.isEmpty()) {
            setState(m_postPreflightState);
            setMessage(m_postPreflightMessage);
            setDetails(m_postPreflightDetails);
            setProgress(m_postPreflightProgress, m_postPreflightProgressText);
        }
        m_postPreflightState.clear();
        m_postPreflightMessage.clear();
        m_postPreflightDetails.clear();
        m_postPreflightProgressText.clear();
        m_postPreflightProgress = -1.0;
        return;
    }
    if (type == QStringLiteral("job_opened")) {
        m_terminalEventSeen = false;
        const qint64 workerProcessId = event.value(QStringLiteral("pid")).toInteger();
        const QString workerIdentity = event.value(QStringLiteral("processIdentity")).toString();
        bool recoveryRecordChanged = false;
        if (workerProcessId > 0 && workerProcessId != m_detachedProcessId) {
            m_detachedProcessId = workerProcessId;
            recoveryRecordChanged = true;
        }
        if (!workerIdentity.isEmpty() && workerIdentity != m_processIdentity) {
            m_processIdentity = workerIdentity;
            recoveryRecordChanged = true;
        }
        if (recoveryRecordChanged && !persistActiveJob())
            appendRecentLog(QStringLiteral("The active worker identity could not be committed to the recovery record."));
        setState(QStringLiteral("running"));
        return;
    }
    if (type == QStringLiteral("stage_started")) {
        const QString currentStage = event.value(QStringLiteral("stage")).toString();
        setState(QStringLiteral("running"));
        setStage(currentStage);
        setMessage(stageLabel(currentStage));
        setProgress(-1.0, QStringLiteral("In progress"));
        return;
    }
    if (type == QStringLiteral("stage_resumed")) {
        const QString currentStage = event.value(QStringLiteral("stage")).toString();
        setStage(currentStage);
        setMessage(QStringLiteral("Verified %1 receipt").arg(stageLabel(currentStage)));
        return;
    }
    if (type == QStringLiteral("stage_progress")) {
        const qint64 completed = event.value(QStringLiteral("completed")).toInteger(-1);
        const qint64 total = event.value(QStringLiteral("total")).toInteger(-1);
        const QString unit = event.value(QStringLiteral("unit")).toString();
        QString text;
        if (unit == QStringLiteral("bytes")) {
            text = total > 0
                       ? QStringLiteral("%1 / %2").arg(formatBytes(completed), formatBytes(total))
                       : formatBytes(completed);
        } else if (unit == QStringLiteral("selected_frames")) {
            text = QStringLiteral("%1 frames selected").arg(formatCount(completed));
        } else {
            text = total > 0
                       ? QStringLiteral("%1 / %2 %3").arg(completed).arg(total).arg(unit)
                       : QStringLiteral("%1 %2").arg(completed).arg(unit);
        }
        setProgress(total > 0 ? std::clamp(static_cast<double>(completed) / total, 0.0, 1.0)
                              : -1.0,
                    text);
        return;
    }
    if (type == QStringLiteral("worker_child_event")) {
        handleChildEvent(event.value(QStringLiteral("child")).toObject());
        return;
    }
    if (type == QStringLiteral("command_output")) {
        appendRecentLog(event.value(QStringLiteral("message")).toString());
        return;
    }
    if (type == QStringLiteral("job_completed")) {
        const QString publishedPath = event.value(QStringLiteral("worldPath")).toString();
        m_terminalEventSeen = true;
        beginPublishedWorldValidation(publishedPath);
        return;
    }
    if (type == QStringLiteral("job_cancelled")) {
        m_terminalEventSeen = true;
        setState(QStringLiteral("cancelled"));
        setMessage(event.value(QStringLiteral("message")).toString());
        setProgress(-1.0, QStringLiteral("Cancelled"));
        return;
    }
    if (type == QStringLiteral("job_failed")
        || type == QStringLiteral("command_failed")) {
        m_terminalEventSeen = true;
        setState(QStringLiteral("failed"));
        setMessage(event.value(QStringLiteral("message")).toString());
        setDetails(event.value(QStringLiteral("details")).toString());
        setProgress(-1.0, QStringLiteral("Failed"));
    }
}

void ReconstructionController::handleChildEvent(const QJsonObject &wrapper)
{
    QJsonObject event = wrapper;
    if (wrapper.value(QStringLiteral("child")).isObject())
        event = wrapper.value(QStringLiteral("child")).toObject();
    const QString type = event.value(QStringLiteral("event")).toString();
    if (type == QStringLiteral("training_progress")) {
        const qint64 step = event.value(QStringLiteral("step")).toInteger();
        const qint64 total = event.value(QStringLiteral("total")).toInteger();
        const qint64 gaussians = event.value(QStringLiteral("gaussians")).toInteger();
        setProgress(total > 0 ? static_cast<double>(step) / total : -1.0,
                    QStringLiteral("Step %1 / %2 · %3 splats")
                        .arg(formatCount(step), formatCount(total), formatCount(gaussians)));
        return;
    }
    if (type == QStringLiteral("checkpoint_saved")) {
        setMessage(QStringLiteral("Checkpoint committed; training continues"));
        return;
    }
    if (type == QStringLiteral("training_resumed")) {
        setMessage(QStringLiteral("Resumed from the last verified checkpoint"));
        return;
    }
    if (type == QStringLiteral("training_failed")) {
        setDetails(event.value(QStringLiteral("message")).toString());
    }
}

void ReconstructionController::processFinished(int exitCode,
                                               QProcess::ExitStatus exitStatus)
{
    if (!m_outputBuffer.trimmed().isEmpty())
        processLine(m_outputBuffer.trimmed());
    m_outputBuffer.clear();
    const ProcessMode completedMode = m_mode;
    m_mode = ProcessMode::None;
    if (completedMode == ProcessMode::Preflight) {
        if (exitStatus == QProcess::CrashExit
            || (exitCode != 0 && m_preflightReady)
            || m_state == QStringLiteral("checking")) {
            m_preflightReady = false;
            emit readinessChanged();
            setState(QStringLiteral("blocked"));
            setMessage(QStringLiteral("Native reconstruction preflight did not complete"));
            setDetails(exitStatus == QProcess::CrashExit
                           ? QStringLiteral("The preflight process crashed.")
                           : QStringLiteral("Worker exit code %1").arg(exitCode));
        }
        emit readinessChanged();
        return;
    }
}

bool ReconstructionController::writeJob(const QVariantList &sources,
                                        const QString &profile,
                                        const QString &worldName)
{
    const QString jobId = QUuid::createUuid().toString(QUuid::WithoutBraces);
    const QString jobsRoot = QDir(QStandardPaths::writableLocation(
                                      QStandardPaths::AppLocalDataLocation))
                                 .filePath(QStringLiteral("reconstruction/jobs"));
    const QString jobRoot = QDir(jobsRoot).filePath(jobId);
    if (!QDir().mkpath(jobRoot)) {
        setState(QStringLiteral("failed"));
        setMessage(QStringLiteral("Unable to create reconstruction workspace"));
        setDetails(jobRoot);
        return false;
    }
    QJsonArray sourceArray;
    for (const QVariant &value : sources)
        sourceArray.append(QJsonObject::fromVariantMap(value.toMap()));
    QJsonObject job {
        { QStringLiteral("schema"), QLatin1StringView(jobSchema) },
        { QStringLiteral("jobId"), jobId },
        { QStringLiteral("pipelineRevision"), m_pipelineRevision },
        { QStringLiteral("createdAt"),
          QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs) },
        { QStringLiteral("worldName"), sanitizeWorldName(worldName) },
        { QStringLiteral("profile"), profile },
        { QStringLiteral("sources"), sourceArray },
    };
    const QString path = QDir(jobRoot).filePath(QStringLiteral("job.json"));
    QSaveFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
        setState(QStringLiteral("failed"));
        setMessage(QStringLiteral("Unable to write reconstruction job"));
        setDetails(file.errorString());
        return false;
    }
    file.write(QJsonDocument(job).toJson(QJsonDocument::Indented));
    if (!file.commit()) {
        setState(QStringLiteral("failed"));
        setMessage(QStringLiteral("Unable to commit reconstruction job"));
        setDetails(file.errorString());
        return false;
    }
    m_jobPath = path;
    m_expectedJobId = jobId;
    m_worldPath.clear();
    m_logPath = QDir(jobRoot).filePath(QStringLiteral("events.jsonl"));
    m_recentLines.clear();
    emit jobChanged();
    emit recentLogChanged();
    return true;
}

void ReconstructionController::beginPublishedWorldValidation(const QString &path)
{
    if (m_artifactValidationActive) {
        protocolFailure(QStringLiteral("More than one world validation was requested for the active job."));
        return;
    }

    m_artifactValidationActive = true;
    setState(QStringLiteral("validating"));
    setStage(QStringLiteral("publish"));
    setMessage(QStringLiteral("Verifying the published Gaussian world"));
    setDetails(QStringLiteral("Checking every declared artifact hash without blocking the interface."));
    setProgress(-1.0, QStringLiteral("Verifying bundle"));
    emit readinessChanged();

    const QString jobPath = m_jobPath;
    const QString expectedJobId = m_expectedJobId;
    const QString pipelineRevision = m_pipelineRevision;
    auto *watcher = new QFutureWatcher<QPair<bool, QString>>(this);
    connect(watcher,
            &QFutureWatcher<QPair<bool, QString>>::finished,
            this,
            [this, watcher, path]() {
                const QPair<bool, QString> result = watcher->result();
                watcher->deleteLater();
                m_artifactValidationActive = false;
                if (!result.first) {
                    setState(QStringLiteral("failed"));
                    setMessage(QStringLiteral("Published world failed the app artifact check"));
                    setDetails(result.second);
                    setProgress(-1.0, QStringLiteral("Failed"));
                } else {
                    m_worldPath = path;
                    emit jobChanged();
                    setState(QStringLiteral("complete"));
                    setStage(QStringLiteral("publish"));
                    setMessage(QStringLiteral("Gaussian world published"));
                    setDetails(m_worldPath);
                    setProgress(1.0, QStringLiteral("Complete"));
                }
                emit readinessChanged();
                if (m_preflightRefreshPending) {
                    m_preflightRefreshPending = false;
                    refreshPreflightAfterJob();
                }
            });
    watcher->setFuture(QtConcurrent::run(
        [path, jobPath, expectedJobId, pipelineRevision]() {
            QString validationError;
            const bool valid = validatePublishedWorld(path,
                                                      jobPath,
                                                      expectedJobId,
                                                      pipelineRevision,
                                                      &validationError);
            return qMakePair(valid, validationError);
        }));
}

bool ReconstructionController::validatePublishedWorld(const QString &path,
                                                       const QString &jobPath,
                                                       const QString &expectedJobId,
                                                       const QString &pipelineRevision,
                                                       QString *error)
{
    const QString jobRoot = QDir(QFileInfo(jobPath).absolutePath()).canonicalPath();
    const QString worldRoot = QDir(path).canonicalPath();
    const Qt::CaseSensitivity pathSensitivity =
#ifdef Q_OS_WIN
        Qt::CaseInsensitive;
#else
        Qt::CaseSensitive;
#endif
    if (jobRoot.isEmpty() || worldRoot.isEmpty()
        || (worldRoot != jobRoot
            && !worldRoot.startsWith(jobRoot + QLatin1Char('/'), pathSensitivity))) {
        if (error)
            *error = QStringLiteral("The published world path is outside this job workspace.");
        return false;
    }
    const QString manifestPath = QDir(worldRoot).filePath(QStringLiteral("world.json"));
    const QString plyPath = QDir(worldRoot).filePath(QStringLiteral("world.ply"));
    QFile manifestFile(manifestPath);
    if (!manifestFile.open(QIODevice::ReadOnly) || !QFileInfo::exists(plyPath)) {
        if (error)
            *error = QStringLiteral("world.json or world.ply is missing from the published bundle.");
        return false;
    }
    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(
        manifestFile.readAll(), &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
        if (error)
            *error = QStringLiteral("world.json is not valid JSON.");
        return false;
    }
    const QJsonObject manifest = document.object();
    const QJsonObject artifacts = manifest.value(QStringLiteral("artifacts")).toObject();
    const QJsonObject hashes = manifest.value(QStringLiteral("hashes")).toObject();
    if (manifest.value(QStringLiteral("schema")).toString()
            != QLatin1StringView(worldSchema)
        || manifest.value(QStringLiteral("worldId")).toString() != expectedJobId
        || manifest.value(QStringLiteral("pipelineRevision")).toString()
               != pipelineRevision
        || artifacts.value(QStringLiteral("ply")).toString()
               != QStringLiteral("world.ply")
        || hashes.value(QStringLiteral("world.ply")).toString().isEmpty()
        || QFileInfo(plyPath).size() <= 0) {
        if (error)
            *error = QStringLiteral("The published bundle identity or artifact manifest is inconsistent.");
        return false;
    }

    const QRegularExpression sha256Pattern(QStringLiteral("^[0-9a-fA-F]{64}$"));
    const auto resolveBundlePath = [&](const QString &relativePath,
                                       bool requireFile,
                                       QString *resolved) {
        const QString normalized = QDir::fromNativeSeparators(relativePath);
        const QString clean = QDir::cleanPath(normalized);
        if (normalized.isEmpty() || QDir::isAbsolutePath(normalized)
            || clean == QStringLiteral("..")
            || clean.startsWith(QStringLiteral("../"))) {
            return false;
        }
        const QFileInfo info(QDir(worldRoot).filePath(clean));
        const QString canonical = info.canonicalFilePath();
        if (canonical.isEmpty()
            || (canonical != worldRoot
                && !canonical.startsWith(worldRoot + QLatin1Char('/'), pathSensitivity))
            || (requireFile && !info.isFile())) {
            return false;
        }
        if (resolved)
            *resolved = canonical;
        return true;
    };

    for (auto iterator = artifacts.constBegin(); iterator != artifacts.constEnd(); ++iterator) {
        const QString relativePath = iterator.value().toString();
        if (!resolveBundlePath(relativePath, false, nullptr)) {
            if (error)
                *error = QStringLiteral("Artifact '%1' has an unsafe or missing bundle path.")
                             .arg(iterator.key());
            return false;
        }
    }

    for (auto iterator = hashes.constBegin(); iterator != hashes.constEnd(); ++iterator) {
        const QString relativePath = iterator.key();
        const QString expectedHash = iterator.value().toString();
        QString artifactPath;
        if (!sha256Pattern.match(expectedHash).hasMatch()
            || !resolveBundlePath(relativePath, true, &artifactPath)) {
            if (error)
                *error = QStringLiteral("Hash entry '%1' is malformed or points outside the bundle.")
                             .arg(relativePath);
            return false;
        }

        QFile artifactFile(artifactPath);
        if (!artifactFile.open(QIODevice::ReadOnly)) {
            if (error)
                *error = QStringLiteral("Unable to read '%1' while verifying the bundle.")
                             .arg(relativePath);
            return false;
        }
        QCryptographicHash hash(QCryptographicHash::Sha256);
        while (!artifactFile.atEnd()) {
            const QByteArray chunk = artifactFile.read(8 * 1024 * 1024);
            if (chunk.isEmpty() && artifactFile.error() != QFileDevice::NoError) {
                if (error)
                    *error = QStringLiteral("I/O failed while hashing '%1'.")
                                 .arg(relativePath);
                return false;
            }
            hash.addData(chunk);
        }
        if (QString::fromLatin1(hash.result().toHex())
                .compare(expectedHash, Qt::CaseInsensitive)
            != 0) {
            if (error)
                *error = QStringLiteral("Artifact hash mismatch: %1").arg(relativePath);
            return false;
        }
    }
    return true;
}

void ReconstructionController::refreshPreflightAfterJob()
{
    m_postPreflightState = m_state;
    m_postPreflightMessage = m_message;
    m_postPreflightDetails = m_details;
    m_postPreflightProgress = m_progress;
    m_postPreflightProgressText = m_progressText;
    QTimer::singleShot(0, this, &ReconstructionController::refreshPreflight);
}

bool ReconstructionController::restoreActiveJob()
{
    QFile file(QDir(m_runtimePath).filePath(QStringLiteral("active-job.json")));
    if (!file.exists())
        return false;
    if (!file.open(QIODevice::ReadOnly)) {
        clearActiveJob();
        return false;
    }
    QJsonParseError error;
    const QJsonDocument document = QJsonDocument::fromJson(file.readAll(), &error);
    if (error.error != QJsonParseError::NoError || !document.isObject()) {
        clearActiveJob();
        return false;
    }
    const QJsonObject active = document.object();
    const QString jobPath = active.value(QStringLiteral("jobPath")).toString();
    const QString jobId = active.value(QStringLiteral("jobId")).toString();
    if (active.value(QStringLiteral("schema")).toString()
            != QStringLiteral("servo.active-reconstruction/v1")
        || !QFileInfo::exists(jobPath) || jobId.isEmpty()) {
        clearActiveJob();
        return false;
    }
    m_jobPath = QFileInfo(jobPath).absoluteFilePath();
    m_expectedJobId = jobId;
    m_logPath = QDir(QFileInfo(m_jobPath).absolutePath())
                    .filePath(QStringLiteral("events.jsonl"));
    m_pipelineRevision = active.value(QStringLiteral("pipelineRevision")).toString();
    m_detachedProcessId = active.value(QStringLiteral("pid")).toInteger();
    m_processIdentity = active.value(QStringLiteral("processIdentity")).toString();
    m_jobLaunchMilliseconds = active.value(QStringLiteral("launchedAtMilliseconds"))
                                  .toInteger(QDateTime::currentMSecsSinceEpoch() - 5000);
    m_eventOffset = 0;
    m_lastEventSequence = 0;
    m_mode = ProcessMode::Job;
    m_jobActive = true;
    m_state = QStringLiteral("running");
    m_message = QStringLiteral("Reattached to the active reconstruction job");
    m_progress = -1.0;
    m_progressText = QStringLiteral("Restoring progress");
    m_jobPollTimer.start();
    QTimer::singleShot(0, this, &ReconstructionController::pollDetachedJob);
    return true;
}

bool ReconstructionController::persistActiveJob() const
{
    if (m_jobPath.isEmpty() || m_expectedJobId.isEmpty())
        return false;
    if (!QDir().mkpath(m_runtimePath))
        return false;
    QSaveFile file(QDir(m_runtimePath).filePath(QStringLiteral("active-job.json")));
    if (!file.open(QIODevice::WriteOnly | QIODevice::Text))
        return false;
    const QJsonObject active {
        { QStringLiteral("schema"), QStringLiteral("servo.active-reconstruction/v1") },
        { QStringLiteral("jobId"), m_expectedJobId },
        { QStringLiteral("jobPath"), m_jobPath },
        { QStringLiteral("pipelineRevision"), m_pipelineRevision },
        { QStringLiteral("pid"), m_detachedProcessId },
        { QStringLiteral("processIdentity"), m_processIdentity },
        { QStringLiteral("launchedAtMilliseconds"), m_jobLaunchMilliseconds },
    };
    const QByteArray payload = QJsonDocument(active).toJson(QJsonDocument::Compact)
                               + '\n';
    if (file.write(payload) != payload.size())
        return false;
    return file.commit();
}

void ReconstructionController::clearActiveJob() const
{
    QFile::remove(QDir(m_runtimePath).filePath(QStringLiteral("active-job.json")));
}

QString ReconstructionController::processIdentity(qint64 processId)
{
    if (processId <= 0)
        return {};
#ifdef Q_OS_WIN
    HANDLE process = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION,
                                 FALSE,
                                 static_cast<DWORD>(processId));
    if (!process)
        return GetLastError() == ERROR_ACCESS_DENIED
                   ? QStringLiteral("access-denied") : QString();
    const DWORD state = WaitForSingleObject(process, 0);
    if (state != WAIT_TIMEOUT) {
        CloseHandle(process);
        return {};
    }
    FILETIME creation;
    FILETIME exit;
    FILETIME kernel;
    FILETIME user;
    if (!GetProcessTimes(process, &creation, &exit, &kernel, &user)) {
        CloseHandle(process);
        return QStringLiteral("alive");
    }
    ULARGE_INTEGER creationTicks;
    creationTicks.LowPart = creation.dwLowDateTime;
    creationTicks.HighPart = creation.dwHighDateTime;
    CloseHandle(process);
    return QStringLiteral("windows-filetime:%1").arg(creationTicks.QuadPart);
#else
    errno = 0;
    if (::kill(static_cast<pid_t>(processId), 0) != 0 && errno != EPERM)
        return {};
    return QStringLiteral("pid:%1").arg(processId);
#endif
}

bool ReconstructionController::processAlive(qint64 processId,
                                            const QString &identity)
{
    const QString currentIdentity = processIdentity(processId);
    if (currentIdentity.isEmpty())
        return false;
    return identity.isEmpty() || currentIdentity == identity
           || currentIdentity == QStringLiteral("access-denied")
           || currentIdentity == QStringLiteral("alive");
}

void ReconstructionController::setState(const QString &value)
{
    if (m_state == value)
        return;
    m_state = value;
    emit stateChanged();
    emit readinessChanged();
}

void ReconstructionController::setStage(const QString &value)
{
    if (m_stage == value)
        return;
    m_stage = value;
    emit stageChanged();
}

void ReconstructionController::setMessage(const QString &value)
{
    if (m_message == value)
        return;
    m_message = value;
    emit messageChanged();
}

void ReconstructionController::setDetails(const QString &value)
{
    if (m_details == value)
        return;
    m_details = value;
    emit detailsChanged();
}

void ReconstructionController::setProgress(double value, const QString &text)
{
    if (qFuzzyCompare(m_progress, value) && m_progressText == text)
        return;
    m_progress = value;
    m_progressText = text;
    emit progressChanged();
}

void ReconstructionController::appendRecentLog(const QString &line)
{
    if (line.trimmed().isEmpty())
        return;
    m_recentLines.append(line.trimmed());
    while (m_recentLines.size() > 24)
        m_recentLines.removeFirst();
    emit recentLogChanged();
}

QString ReconstructionController::locatePython()
{
    const QString explicitPath = qEnvironmentVariable("SERVO_RECON_PYTHON");
    if (QFileInfo::exists(explicitPath))
        return QFileInfo(explicitPath).absoluteFilePath();
    const QString localAppData = qEnvironmentVariable("LOCALAPPDATA");
    const QString managed = QDir(localAppData).filePath(
        QStringLiteral("Servo/reconstruction/venv-py311-cu128/Scripts/python.exe"));
    if (QFileInfo::exists(managed))
        return QFileInfo(managed).absoluteFilePath();
    return QStandardPaths::findExecutable(QStringLiteral("python"));
}

QString ReconstructionController::locateWorker()
{
    const QString explicitPath = qEnvironmentVariable("SERVO_RECON_WORKER");
    if (QFileInfo::exists(explicitPath))
        return QFileInfo(explicitPath).absoluteFilePath();
#ifdef SERVO_RECONSTRUCTION_SOURCE_DIR
    const QString source = QDir(QStringLiteral(SERVO_RECONSTRUCTION_SOURCE_DIR))
                               .filePath(QStringLiteral("servo_worker.py"));
    if (QFileInfo::exists(source))
        return QFileInfo(source).absoluteFilePath();
#endif
    const QString installed = QDir(QCoreApplication::applicationDirPath())
                                  .filePath(QStringLiteral("reconstruction/servo_worker.py"));
    return QFileInfo::exists(installed) ? QFileInfo(installed).absoluteFilePath()
                                        : QString();
}

QString ReconstructionController::stageLabel(const QString &stage)
{
    if (stage == QStringLiteral("hash"))
        return QStringLiteral("Hashing source media");
    if (stage == QStringLiteral("extract"))
        return QStringLiteral("Selecting sharp overlapping frames");
    if (stage == QStringLiteral("pose"))
        return QStringLiteral("Recovering cameras and sparse geometry");
    if (stage == QStringLiteral("train"))
        return QStringLiteral("Optimizing the Gaussian world");
    if (stage == QStringLiteral("validate"))
        return QStringLiteral("Validating quality and artifact structure");
    if (stage == QStringLiteral("publish"))
        return QStringLiteral("Publishing the world atomically");
    return stage;
}

QString ReconstructionController::formatCount(qint64 value)
{
    return QLocale().toString(value);
}

QString ReconstructionController::sanitizeWorldName(const QString &value)
{
    QString result = value.trimmed();
    if (result.isEmpty())
        result = QStringLiteral("Observed world");
    result.replace(QRegularExpression(QStringLiteral(R"([<>:"/\\|?*\x00-\x1F])")),
                   QStringLiteral("_"));
    return result.left(96);
}
