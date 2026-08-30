#pragma once

#include <QDir>
#include <QFileInfo>
#include <QString>
#include <QtGlobal>

// The Python worker deliberately owns its data under
// %LOCALAPPDATA%/Servo/reconstruction (or ~/.servo/reconstruction outside
// Windows).  Keep the Qt front end on that exact contract so a verified world
// becomes visible in the library immediately after publication.
namespace Servo::ReconstructionPaths {

inline QString localRuntimeRootFor(const QString &localAppData,
                                   const QString &configuredRoot = {})
{
    const QString overrideRoot = configuredRoot.trimmed();
    if (!overrideRoot.isEmpty())
        return QDir::cleanPath(QFileInfo(overrideRoot).absoluteFilePath());
    if (!localAppData.trimmed().isEmpty())
        return QDir(localAppData).filePath(QStringLiteral("Servo/reconstruction"));
    return QDir(QDir::homePath()).filePath(QStringLiteral(".servo/reconstruction"));
}

inline QString localRuntimeRoot()
{
    const QString configured = qEnvironmentVariable("SERVO_RECONSTRUCTION_ROOT").trimmed();
    if (!configured.isEmpty())
        return localRuntimeRootFor(qEnvironmentVariable("LOCALAPPDATA"), configured);
#ifdef SERVO_PROJECT_SOURCE_DIR
    // A source build moved to another drive owns its reconstruction runtime
    // beside that checkout. This keeps D:\Servo self-contained when the app is
    // launched directly instead of requiring an ephemeral shell variable.
    const QString projectRuntime = QDir(QStringLiteral(SERVO_PROJECT_SOURCE_DIR))
                                       .filePath(QStringLiteral("runtime/reconstruction"));
    if (QFileInfo(projectRuntime).isDir())
        return QDir::cleanPath(projectRuntime);
#endif
    return localRuntimeRootFor(qEnvironmentVariable("LOCALAPPDATA"));
}

} // namespace Servo::ReconstructionPaths
