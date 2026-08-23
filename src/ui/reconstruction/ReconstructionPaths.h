#pragma once

#include <QDir>
#include <QString>
#include <QtGlobal>

// The Python worker deliberately owns its data under
// %LOCALAPPDATA%/Servo/reconstruction (or ~/.servo/reconstruction outside
// Windows).  Keep the Qt front end on that exact contract so a verified world
// becomes visible in the library immediately after publication.
namespace Servo::ReconstructionPaths {

inline QString localRuntimeRootFor(const QString &localAppData)
{
    if (!localAppData.trimmed().isEmpty())
        return QDir(localAppData).filePath(QStringLiteral("Servo/reconstruction"));
    return QDir(QDir::homePath()).filePath(QStringLiteral(".servo/reconstruction"));
}

inline QString localRuntimeRoot()
{
    return localRuntimeRootFor(qEnvironmentVariable("LOCALAPPDATA"));
}

} // namespace Servo::ReconstructionPaths
