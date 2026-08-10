#pragma once

#include <QElapsedTimer>
#include <QObject>
#include <QPointer>
#include <QQuickWindow>
#include <QScreen>
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
    Q_PROPERTY(int presentedFramesPerSecond READ presentedFramesPerSecond NOTIFY metricsChanged)
    Q_PROPERTY(QString presentationRateText READ presentationRateText NOTIFY metricsChanged)
    Q_PROPERTY(double displayRefreshRate READ displayRefreshRate NOTIFY metricsChanged)
    Q_PROPERTY(QString displayRefreshText READ displayRefreshText NOTIFY metricsChanged)
    Q_PROPERTY(QString graphicsApi READ graphicsApi NOTIFY graphicsApiChanged)
    Q_PROPERTY(QString graphicsDevice READ graphicsDevice NOTIFY graphicsApiChanged)
    Q_PROPERTY(QString graphicsDeviceType READ graphicsDeviceType NOTIFY graphicsApiChanged)
    Q_PROPERTY(bool vulkanReady READ vulkanReady NOTIFY graphicsApiChanged)
    Q_PROPERTY(bool sceneGraphReady READ sceneGraphReady NOTIFY graphicsApiChanged)

public:
    explicit RuntimeMetrics(QObject *parent = nullptr);

    double cpuPercent() const;
    quint64 residentMemoryBytes() const;
    QString residentMemoryText() const;
    int uiFramesPerSecond() const;
    QString frameRateText() const;
    int presentedFramesPerSecond() const;
    QString presentationRateText() const;
    double displayRefreshRate() const;
    QString displayRefreshText() const;
    QString graphicsApi() const;
    QString graphicsDevice() const;
    QString graphicsDeviceType() const;
    bool vulkanReady() const;
    bool sceneGraphReady() const;

    Q_INVOKABLE void attachWindow(QQuickWindow *window);

signals:
    void metricsChanged();
    void graphicsApiChanged();

private slots:
    void sample();

private:
    void queryGraphicsApi();
    void updateScreen(QScreen *screen);
    void setGraphicsInfo(const QString &api,
                         const QString &device,
                         const QString &deviceType,
                         bool ready);

    QTimer m_sampleTimer;
    QPointer<QQuickWindow> m_window;
    QPointer<QScreen> m_screen;
    QElapsedTimer m_frameSampleClock;
    std::atomic<int> m_frameCount { 0 };
    double m_cpuPercent = -1.0;
    quint64 m_residentMemoryBytes = 0;
    int m_uiFramesPerSecond = -1;
    double m_displayRefreshRate = 0.0;
    QString m_graphicsApi = QStringLiteral("Initializing");
    QString m_graphicsDevice = QStringLiteral("Detecting");
    QString m_graphicsDeviceType = QStringLiteral("Unknown");
    bool m_sceneGraphReady = false;

#ifdef Q_OS_WIN
    quint64 m_previousSystemTime = 0;
    quint64 m_previousProcessTime = 0;
#endif
};
