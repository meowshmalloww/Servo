#include "RuntimeMetrics.h"

#include <QMetaObject>
#include <QQuickWindow>
#include <QScreen>
#include <QSGRendererInterface>
#include <rhi/qrhi.h>

#ifdef Q_OS_WIN
#include <windows.h>
#include <psapi.h>
#endif

namespace {
#ifdef Q_OS_WIN
quint64 fileTimeValue(const FILETIME &time)
{
    ULARGE_INTEGER value;
    value.LowPart = time.dwLowDateTime;
    value.HighPart = time.dwHighDateTime;
    return value.QuadPart;
}

bool readCpuTimes(quint64 &systemTime, quint64 &processTime)
{
    FILETIME idle;
    FILETIME kernel;
    FILETIME user;
    FILETIME creation;
    FILETIME exit;
    FILETIME processKernel;
    FILETIME processUser;

    if (!GetSystemTimes(&idle, &kernel, &user)
        || !GetProcessTimes(GetCurrentProcess(),
                            &creation,
                            &exit,
                            &processKernel,
                            &processUser)) {
        return false;
    }

    systemTime = fileTimeValue(kernel) + fileTimeValue(user);
    processTime = fileTimeValue(processKernel) + fileTimeValue(processUser);
    return true;
}
#endif

QString graphicsApiName(QSGRendererInterface::GraphicsApi api)
{
    switch (api) {
    case QSGRendererInterface::OpenGL:
        return QStringLiteral("OpenGL");
    case QSGRendererInterface::Direct3D11:
        return QStringLiteral("D3D11");
    case QSGRendererInterface::Direct3D12:
        return QStringLiteral("D3D12");
    case QSGRendererInterface::Vulkan:
        return QStringLiteral("Vulkan");
    case QSGRendererInterface::Metal:
        return QStringLiteral("Metal");
    case QSGRendererInterface::Software:
        return QStringLiteral("Software");
    case QSGRendererInterface::Null:
        return QStringLiteral("Null");
    default:
        return QStringLiteral("Unknown");
    }
}

QString graphicsDeviceTypeName(QRhiDriverInfo::DeviceType type)
{
    switch (type) {
    case QRhiDriverInfo::DiscreteDevice:
        return QStringLiteral("Discrete GPU");
    case QRhiDriverInfo::IntegratedDevice:
        return QStringLiteral("Integrated GPU");
    case QRhiDriverInfo::ExternalDevice:
        return QStringLiteral("External GPU");
    case QRhiDriverInfo::VirtualDevice:
        return QStringLiteral("Virtual GPU");
    case QRhiDriverInfo::CpuDevice:
        return QStringLiteral("CPU renderer");
    default:
        return QStringLiteral("Unknown");
    }
}
} // namespace

RuntimeMetrics::RuntimeMetrics(QObject *parent)
    : QObject(parent)
{
    m_sampleTimer.setInterval(1000);
    // Telemetry does not need millisecond precision. A coarse timer lets the
    // OS coalesce this wakeup with other work and reduces background overhead.
    m_sampleTimer.setTimerType(Qt::CoarseTimer);
    connect(&m_sampleTimer, &QTimer::timeout, this, &RuntimeMetrics::sample);

#ifdef Q_OS_WIN
    readCpuTimes(m_previousSystemTime, m_previousProcessTime);
#endif

    m_sampleTimer.start();
    m_frameSampleClock.start();
    sample();
}

double RuntimeMetrics::cpuPercent() const
{
    return m_cpuPercent;
}

quint64 RuntimeMetrics::residentMemoryBytes() const
{
    return m_residentMemoryBytes;
}

QString RuntimeMetrics::residentMemoryText() const
{
    if (m_residentMemoryBytes == 0)
        return QStringLiteral("--");

    const double mebibytes = static_cast<double>(m_residentMemoryBytes) / (1024.0 * 1024.0);
    return QStringLiteral("%1 MB").arg(mebibytes, 0, 'f', mebibytes < 100.0 ? 1 : 0);
}

int RuntimeMetrics::uiFramesPerSecond() const
{
    return m_uiFramesPerSecond;
}

QString RuntimeMetrics::frameRateText() const
{
    return presentationRateText();
}

int RuntimeMetrics::presentedFramesPerSecond() const
{
    return m_uiFramesPerSecond;
}

QString RuntimeMetrics::presentationRateText() const
{
    return m_uiFramesPerSecond <= 2
               ? QStringLiteral("Idle")
               : QStringLiteral("%1 fps").arg(m_uiFramesPerSecond);
}

double RuntimeMetrics::displayRefreshRate() const
{
    return m_displayRefreshRate;
}

QString RuntimeMetrics::displayRefreshText() const
{
    if (m_displayRefreshRate <= 0.0)
        return QStringLiteral("--");

    const int rounded = qRound(m_displayRefreshRate);
    if (qAbs(m_displayRefreshRate - rounded) < 0.05)
        return QStringLiteral("%1 Hz").arg(rounded);
    return QStringLiteral("%1 Hz").arg(m_displayRefreshRate, 0, 'f', 1);
}

QString RuntimeMetrics::graphicsApi() const
{
    return m_graphicsApi;
}

QString RuntimeMetrics::graphicsDevice() const
{
    return m_graphicsDevice;
}

QString RuntimeMetrics::graphicsDeviceType() const
{
    return m_graphicsDeviceType;
}

bool RuntimeMetrics::vulkanReady() const
{
    return m_sceneGraphReady && m_graphicsApi == QStringLiteral("Vulkan");
}

bool RuntimeMetrics::sceneGraphReady() const
{
    return m_sceneGraphReady;
}

void RuntimeMetrics::attachWindow(QQuickWindow *window)
{
    if (m_window == window)
        return;

    if (m_window)
        disconnect(m_window, nullptr, this, nullptr);
    if (m_screen)
        disconnect(m_screen, nullptr, this, nullptr);

    m_window = window;
    m_screen = nullptr;
    m_frameCount.store(0, std::memory_order_relaxed);
    m_uiFramesPerSecond = -1;
    m_frameSampleClock.restart();

    if (!m_window) {
        setGraphicsInfo(QStringLiteral("Unavailable"),
                        QStringLiteral("Unavailable"),
                        QStringLiteral("Unknown"),
                        false);
        updateScreen(nullptr);
        return;
    }

    connect(m_window,
            &QQuickWindow::frameSwapped,
            this,
            [this]() { m_frameCount.fetch_add(1, std::memory_order_relaxed); },
            Qt::DirectConnection);

    connect(m_window,
            &QQuickWindow::sceneGraphInitialized,
            this,
            &RuntimeMetrics::queryGraphicsApi,
            Qt::DirectConnection);

    connect(m_window,
            &QWindow::screenChanged,
            this,
            &RuntimeMetrics::updateScreen);

    connect(m_window,
            &QQuickWindow::sceneGraphInvalidated,
            this,
            [this]() {
                QMetaObject::invokeMethod(
                    this,
                    [this]() {
                        setGraphicsInfo(QStringLiteral("Unavailable"),
                                        QStringLiteral("Unavailable"),
                                        QStringLiteral("Unknown"),
                                        false);
                    },
                    Qt::QueuedConnection);
            },
            Qt::DirectConnection);

    connect(m_window, &QObject::destroyed, this, [this]() {
        m_window = nullptr;
        updateScreen(nullptr);
        setGraphicsInfo(QStringLiteral("Unavailable"),
                        QStringLiteral("Unavailable"),
                        QStringLiteral("Unknown"),
                        false);
    });

    updateScreen(m_window->screen());
    queryGraphicsApi();
}

void RuntimeMetrics::sample()
{
    const int frames = m_frameCount.exchange(0, std::memory_order_relaxed);
    const qint64 elapsedMilliseconds = m_frameSampleClock.isValid()
                                            ? m_frameSampleClock.restart()
                                            : 1000;
    m_uiFramesPerSecond = elapsedMilliseconds > 0
                              ? qRound((1000.0 * frames) / elapsedMilliseconds)
                              : frames;

#ifdef Q_OS_WIN
    quint64 systemTime = 0;
    quint64 processTime = 0;
    if (readCpuTimes(systemTime, processTime)) {
        const quint64 systemDelta = systemTime - m_previousSystemTime;
        const quint64 processDelta = processTime - m_previousProcessTime;
        if (m_previousSystemTime != 0 && systemDelta != 0) {
            m_cpuPercent = qBound(0.0,
                                  (100.0 * static_cast<double>(processDelta))
                                      / static_cast<double>(systemDelta),
                                  100.0);
        }
        m_previousSystemTime = systemTime;
        m_previousProcessTime = processTime;
    }

    PROCESS_MEMORY_COUNTERS_EX counters;
    counters.cb = sizeof(counters);
    if (GetProcessMemoryInfo(GetCurrentProcess(),
                             reinterpret_cast<PROCESS_MEMORY_COUNTERS *>(&counters),
                             sizeof(counters))) {
        m_residentMemoryBytes = static_cast<quint64>(counters.WorkingSetSize);
    }
#endif

    emit metricsChanged();
}

void RuntimeMetrics::updateScreen(QScreen *screen)
{
    if (m_screen == screen) {
        const double nextRate = screen ? screen->refreshRate() : 0.0;
        if (!qFuzzyCompare(m_displayRefreshRate, nextRate)) {
            m_displayRefreshRate = nextRate;
            emit metricsChanged();
        }
        return;
    }

    if (m_screen)
        disconnect(m_screen, nullptr, this, nullptr);
    m_screen = screen;
    m_displayRefreshRate = screen ? screen->refreshRate() : 0.0;
    if (m_screen) {
        connect(m_screen,
                &QScreen::refreshRateChanged,
                this,
                [this](qreal refreshRate) {
                    m_displayRefreshRate = refreshRate;
                    emit metricsChanged();
                });
    }
    emit metricsChanged();
}

void RuntimeMetrics::queryGraphicsApi()
{
    if (!m_window)
        return;

    QSGRendererInterface *rendererInterface = m_window->rendererInterface();
    const QString apiName = graphicsApiName(rendererInterface->graphicsApi());
    QString deviceName = QStringLiteral("Unavailable");
    QString deviceType = QStringLiteral("Unknown");

    if (auto *rhi = static_cast<QRhi *>(rendererInterface->getResource(
            m_window,
            QSGRendererInterface::RhiResource))) {
        const QRhiDriverInfo driverInfo = rhi->driverInfo();
        deviceName = QString::fromUtf8(driverInfo.deviceName);
        deviceType = graphicsDeviceTypeName(driverInfo.deviceType);
    }

    QMetaObject::invokeMethod(
        this,
        [this, apiName, deviceName, deviceType]() {
            setGraphicsInfo(apiName,
                            deviceName,
                            deviceType,
                            apiName == QStringLiteral("Vulkan"));
        },
        Qt::QueuedConnection);
}

void RuntimeMetrics::setGraphicsInfo(const QString &api,
                                     const QString &device,
                                     const QString &deviceType,
                                     bool ready)
{
    if (m_graphicsApi == api && m_graphicsDevice == device
        && m_graphicsDeviceType == deviceType && m_sceneGraphReady == ready) {
        return;
    }

    m_graphicsApi = api;
    m_graphicsDevice = device;
    m_graphicsDeviceType = deviceType;
    m_sceneGraphReady = ready;
    emit graphicsApiChanged();
}
