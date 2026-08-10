#include <QFile>
#include <QGuiApplication>
#include <QIcon>
#include <QMutex>
#include <QMutexLocker>
#include <QQmlApplicationEngine>
#include <QQuickGraphicsConfiguration>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QSurfaceFormat>
#include <QWindow>
#include <QtLogging>

#ifdef Q_OS_WIN
#include <dwmapi.h>
#include <windows.h>

extern "C" {
// Ask hybrid-graphics drivers to run Servo on the high-performance adapter.
// The Vulkan device is still verified after Qt initializes the scene graph.
__declspec(dllexport) DWORD NvOptimusEnablement = 0x00000001;
__declspec(dllexport) int AmdPowerXpressRequestHighPerformance = 1;
}
#endif

namespace {
QFile *servoLogFile = nullptr;
QMutex servoLogMutex;
QtMessageHandler previousMessageHandler = nullptr;

#ifdef Q_OS_WIN
void applyDarkWindowChrome(QWindow *window)
{
    const BOOL enabled = TRUE;
    const HWND handle = reinterpret_cast<HWND>(window->winId());
    constexpr DWORD immersiveDarkMode = 20;
    constexpr DWORD immersiveDarkModeLegacy = 19;

    if (FAILED(DwmSetWindowAttribute(handle,
                                     immersiveDarkMode,
                                     &enabled,
                                     sizeof(enabled)))) {
        DwmSetWindowAttribute(handle,
                              immersiveDarkModeLegacy,
                              &enabled,
                              sizeof(enabled));
    }
}
#endif

void servoMessageHandler(QtMsgType type,
                         const QMessageLogContext &context,
                         const QString &message)
{
    const QByteArray formatted = qFormatLogMessage(type, context, message).toUtf8();

    if (servoLogFile) {
        QMutexLocker locker(&servoLogMutex);
        servoLogFile->write(formatted);
        servoLogFile->write("\n");
        servoLogFile->flush();
    }

    if (previousMessageHandler)
        previousMessageHandler(type, context, message);
}
} // namespace

int main(int argc, char *argv[])
{
    // Keep presentation synchronized with the active display while allowing
    // static editor surfaces to remain event-driven.
    QSurfaceFormat surfaceFormat;
    surfaceFormat.setSwapBehavior(QSurfaceFormat::DoubleBuffer);
    surfaceFormat.setSwapInterval(1);
    QSurfaceFormat::setDefaultFormat(surfaceFormat);

    QQuickStyle::setStyle(QStringLiteral("Basic"));

    // Servo deliberately has no OpenGL, WebGL, or Direct3D renderer fallback.
    // Qt reports a scene-graph initialization error when Vulkan is unavailable.
    qputenv("QSG_RHI_BACKEND", "vulkan");
    QQuickWindow::setGraphicsApi(QSGRendererInterface::Vulkan);

    QFile logFile;
    const QString logPath = qEnvironmentVariable("SERVO_QML_LOG");
    if (!logPath.isEmpty()) {
        logFile.setFileName(logPath);
        if (logFile.open(QIODevice::WriteOnly | QIODevice::Truncate | QIODevice::Text)) {
            servoLogFile = &logFile;
            previousMessageHandler = qInstallMessageHandler(servoMessageHandler);
        }
    }

    QGuiApplication app(argc, argv);
    QCoreApplication::setOrganizationName(QStringLiteral("Servo"));
    QCoreApplication::setOrganizationDomain(QStringLiteral("servo.local"));
    QCoreApplication::setApplicationName(QStringLiteral("Servo"));
    QCoreApplication::setApplicationVersion(QStringLiteral("0.2.0"));
    app.setWindowIcon(QIcon(QStringLiteral(":/qt/qml/Servo/assets/servo-logo.png")));

    QQmlApplicationEngine engine;
    QObject::connect(
        &engine,
        &QQmlApplicationEngine::objectCreated,
        &app,
        [&app](QObject *object, const QUrl &) {
            auto *window = qobject_cast<QQuickWindow *>(object);
            if (!window)
                return;

            QQuickGraphicsConfiguration graphicsConfiguration;
            const bool validationEnabled =
                qEnvironmentVariableIntValue("SERVO_VULKAN_VALIDATION") != 0;
            graphicsConfiguration.setDebugLayer(validationEnabled);
            graphicsConfiguration.setDebugMarkers(validationEnabled);
            graphicsConfiguration.setTimestamps(true);
            window->setGraphicsConfiguration(graphicsConfiguration);

            QObject::connect(
                window,
                &QQuickWindow::sceneGraphError,
                &app,
                [&app](QQuickWindow::SceneGraphError, const QString &message) {
                    qCritical().noquote()
                        << "Servo requires a working Vulkan renderer:" << message;
                    QMetaObject::invokeMethod(
                        &app,
                        []() { QCoreApplication::exit(2); },
                        Qt::QueuedConnection);
                });

            QObject::connect(
                window,
                &QQuickWindow::sceneGraphInitialized,
                &app,
                [window, &app]() {
                    if (window->rendererInterface()->graphicsApi()
                        == QSGRendererInterface::Vulkan) {
                        qInfo() << "Servo scene graph initialized with Vulkan";
                        return;
                    }

                    qCritical()
                        << "Servo refused to start because the active renderer is not Vulkan";
                    QMetaObject::invokeMethod(
                        &app,
                        []() { QCoreApplication::exit(3); },
                        Qt::QueuedConnection);
                },
                Qt::DirectConnection);

#ifdef Q_OS_WIN
            applyDarkWindowChrome(window);
#endif

            window->show();
        });
    QObject::connect(
        &engine,
        &QQmlApplicationEngine::objectCreationFailed,
        &app,
        []() { QCoreApplication::exit(-1); },
        Qt::QueuedConnection);

    engine.loadFromModule("Servo", "Main");
    const int result = QGuiApplication::exec();

    if (servoLogFile) {
        qInstallMessageHandler(previousMessageHandler);
        servoLogFile = nullptr;
        logFile.close();
    }

    return result;
}
