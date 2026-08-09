#pragma once

#include <QObject>
#include <QPointer>
#include <QQuickWindow>
#include <QTimer>
#include <QtQmlIntegration>

#include <atomic>

class RuntimeMetrics final : public QObject
{
    Q_OBJECT
    QML_NAMED_ELEMENT(RuntimeMetrics)
    QML_SINGLETON

    Q_PROPERTY(double cpuPercent READ cpuPercent NOTIFY metricsChanged)
    Q_PROPERTY(quint64 residentMemoryBytes READ residentMemoryBytes NOTIFY metricsChanged)
    Q_PROPERTY(QString residentMemoryText READ residentMemoryText NOTIFY metricsChanged)
    Q_PROPERTY(int uiFramesPerSecond READ uiFramesPerSecond NOTIFY metricsChanged)
    Q_PROPERTY(QString frameRateText READ frameRateText NOTIFY metricsChanged)
    Q_PROPERTY(QString graphicsApi READ graphicsApi NOTIFY graphicsApiChanged)
    Q_PROPERTY(bool sceneGraphReady READ sceneGraphReady NOTIFY graphicsApiChanged)

public:
    explicit RuntimeMetrics(QObject *parent = nullptr);

    double cpuPercent() const;
    quint64 residentMemoryBytes() const;
    QString residentMemoryText() const;
    int uiFramesPerSecond() const;
    QString frameRateText() const;
    QString graphicsApi() const;
    bool sceneGraphReady() const;

    Q_INVOKABLE void attachWindow(QQuickWindow *window);

signals:
    void metricsChanged();
    void graphicsApiChanged();

private slots:
    void sample();

private:
    void queryGraphicsApi();
    void setGraphicsApi(const QString &name, bool ready);

    QTimer m_sampleTimer;
    QPointer<QQuickWindow> m_window;
    std::atomic<int> m_frameCount { 0 };
    double m_cpuPercent = -1.0;
    quint64 m_residentMemoryBytes = 0;
    int m_uiFramesPerSecond = -1;
    QString m_graphicsApi = QStringLiteral("Initializing");
    bool m_sceneGraphReady = false;

#ifdef Q_OS_WIN
    quint64 m_previousSystemTime = 0;
    quint64 m_previousProcessTime = 0;
#endif
};
