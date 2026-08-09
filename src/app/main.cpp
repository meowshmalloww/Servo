#include <QFile>
#include <QGuiApplication>
#include <QMutex>
#include <QMutexLocker>
#include <QQmlApplicationEngine>
#include <QQuickStyle>
#include <QSurfaceFormat>
#include <QWindow>
#include <QtLogging>

#ifdef Q_OS_WIN
#include <dwmapi.h>
#include <windows.h>
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
    // Keep presentation synchronized with the active display. A 120 Hz display
    // can therefore present the UI at 120 Hz without a timer-driven redraw loop.
    QSurfaceFormat surfaceFormat;
    surfaceFormat.setSwapBehavior(QSurfaceFormat::DoubleBuffer);
    surfaceFormat.setSwapInterval(1);
    QSurfaceFormat::setDefaultFormat(surfaceFormat);

    QQuickStyle::setStyle(QStringLiteral("Basic"));

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

    QQmlApplicationEngine engine;
    QObject::connect(
        &engine,
        &QQmlApplicationEngine::objectCreated,
        &app,
        [](QObject *object, const QUrl &) {
#ifdef Q_OS_WIN
            if (auto *window = qobject_cast<QWindow *>(object))
                applyDarkWindowChrome(window);
#else
            Q_UNUSED(object);
#endif
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
