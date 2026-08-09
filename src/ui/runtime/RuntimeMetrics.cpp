#include "RuntimeMetrics.h"

#include <QMetaObject>
#include <QQuickWindow>
#include <QSGRendererInterface>

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
} // namespace

RuntimeMetrics::RuntimeMetrics(QObject *parent)
    : QObject(parent)
{
    m_sampleTimer.setInterval(1000);
    m_sampleTimer.setTimerType(Qt::VeryCoarseTimer);
    connect(&m_sampleTimer, &QTimer::timeout, this, &RuntimeMetrics::sample);

#ifdef Q_OS_WIN
    readCpuTimes(m_previousSystemTime, m_previousProcessTime);
#endif

    m_sampleTimer.start();
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
    return m_uiFramesPerSecond < 0
               ? QStringLiteral("Idle")
               : QString::number(m_uiFramesPerSecond);
}

QString RuntimeMetrics::graphicsApi() const
{
    return m_graphicsApi;
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

    m_window = window;
    m_frameCount.store(0, std::memory_order_relaxed);

    if (!m_window) {
        setGraphicsApi(QStringLiteral("Unavailable"), false);
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
            &QQuickWindow::sceneGraphInvalidated,
            this,
            [this]() {
                QMetaObject::invokeMethod(
                    this,
                    [this]() { setGraphicsApi(QStringLiteral("Unavailable"), false); },
                    Qt::QueuedConnection);
            },
            Qt::DirectConnection);

    connect(m_window, &QObject::destroyed, this, [this]() {
        m_window = nullptr;
        setGraphicsApi(QStringLiteral("Unavailable"), false);
    });

    queryGraphicsApi();
}

void RuntimeMetrics::sample()
{
    const int frames = m_frameCount.exchange(0, std::memory_order_relaxed);
    m_uiFramesPerSecond = frames > 2 ? frames : -1;

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

void RuntimeMetrics::queryGraphicsApi()
{
    if (!m_window)
        return;

    const QString name = graphicsApiName(m_window->rendererInterface()->graphicsApi());
    QMetaObject::invokeMethod(
        this,
        [this, name]() { setGraphicsApi(name, name != QStringLiteral("Unknown")); },
        Qt::QueuedConnection);
}

void RuntimeMetrics::setGraphicsApi(const QString &name, bool ready)
{
    if (m_graphicsApi == name && m_sceneGraphReady == ready)
        return;

    m_graphicsApi = name;
    m_sceneGraphReady = ready;
    emit graphicsApiChanged();
}
