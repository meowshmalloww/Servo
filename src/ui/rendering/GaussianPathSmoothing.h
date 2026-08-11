#pragma once

#include <QVector>
#include <QVector3D>

namespace Servo {

// Smooth only the navigation-height component of an observed camera path.
// The robust local line fit preserves sustained grades while rejecting
// high-frequency pose bounce. Reconstruction cameras and world geometry are
// never changed; this is solely the path used by the interactive viewer.
QVector<QVector3D> smoothNavigationHeights(const QVector<QVector3D> &path,
                                            const QVector3D &navigationUp,
                                            qsizetype radius = 3);

} // namespace Servo
