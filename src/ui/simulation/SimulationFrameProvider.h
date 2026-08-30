#pragma once

#include <QImage>
#include <QMutex>
#include <QQuickImageProvider>
#include <QString>

class SimulationFrameProvider final : public QQuickImageProvider
{
public:
    SimulationFrameProvider();

    QImage requestImage(const QString &id, QSize *size, const QSize &requestedSize) override;
    void publish(const QImage &image, const QString &sessionId, quint64 frameId);

private:
    QMutex m_mutex;
    QImage m_image;
    QString m_sessionId;
    quint64 m_frameId = 0;
};
