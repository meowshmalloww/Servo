#include "SimulationFrameProvider.h"

#include <QMutexLocker>

SimulationFrameProvider::SimulationFrameProvider()
    : QQuickImageProvider(QQuickImageProvider::Image)
{
}

QImage SimulationFrameProvider::requestImage(const QString &id,
                                              QSize *size,
                                              const QSize &requestedSize)
{
    Q_UNUSED(id);
    QMutexLocker locker(&m_mutex);
    QImage result = m_image;
    if (size)
        *size = result.size();
    if (!requestedSize.isEmpty() && !result.isNull())
        result = result.scaled(requestedSize, Qt::KeepAspectRatio, Qt::SmoothTransformation);
    return result;
}

void SimulationFrameProvider::publish(const QImage &image,
                                      const QString &sessionId,
                                      quint64 frameId)
{
    QMutexLocker locker(&m_mutex);
    if (sessionId == m_sessionId && frameId < m_frameId)
        return;
    m_image = image.copy();
    m_sessionId = sessionId;
    m_frameId = frameId;
}
