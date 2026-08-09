#include <QGuiApplication>
#include <QFile>
#include <QMutex>
#include <QMutexLocker>
#include <QQmlApplicationEngine>
#include <QtLogging>

namespace {
QFile *servoLogFile = nullptr;
QMutex servoLogMutex;
QtMessageHandler previousMessageHandler = nullptr;

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

    QQmlApplicationEngine engine;
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
