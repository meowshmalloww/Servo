#pragma once

#include <QColor>
#include <QImage>
#include <QQuickRhiItem>
#include <QString>
#include <QUrl>
#include <QVector3D>
#include <QtQmlIntegration>

#include <memory>

struct GaussianSceneData;

namespace Servo::Rendering {

// The finite splat layer is intentionally not used for the distant sky.  This
// descriptor carries only pixels that were actually observed by the semantic
// stage; transparent texels are explicitly unknown rather than inpainted.
struct GaussianWorldEnvironment
{
    QVector3D backgroundColorSrgb { 0.0f, 0.0f, 0.0f };
    QImage observedDirectionalRgba;
    bool hasObservedDirectionalEnvironment = false;
};

// Reads and verifies the display-referred fallback plus optional observed-only
// directional sky evidence from the world manifest beside a published PLY.
// Standalone PLYs and verified r6 bundles retain the historical black fallback;
// a bundle that claims the new directional source fails closed if its PNG or
// provenance is malformed.
bool readGaussianWorldEnvironment(const QString &plyPath,
                                  GaussianWorldEnvironment *environment,
                                  QString *error = nullptr);

// Reads the display-referred background used by gsplat from the world manifest
// next to a published PLY. Standalone PLYs and verified r6 bundles retain the
// historical black fallback; manifests that claim the r7 pipeline are strict.
bool readGaussianWorldBackground(const QString &plyPath,
                                 QVector3D *backgroundColorSrgb,
                                 QString *error = nullptr);

// Appearance is composited over the world background. Diagnostic render modes
// intentionally use black so their values cannot be confused with appearance.
QColor gaussianAccumulationClearColor(const QVector3D &backgroundColorSrgb,
                                      int visualizationMode);

} // namespace Servo::Rendering

class GaussianSplatView : public QQuickRhiItem
{
    Q_OBJECT
    QML_NAMED_ELEMENT(GaussianSplatView)

    Q_PROPERTY(QUrl source READ source WRITE setSource NOTIFY sourceChanged)
    Q_PROPERTY(bool loading READ loading NOTIFY loadingChanged)
    Q_PROPERTY(bool ready READ ready NOTIFY sceneChanged)
    Q_PROPERTY(QString statusText READ statusText NOTIFY statusChanged)
    Q_PROPERTY(QString errorString READ errorString NOTIFY statusChanged)
    Q_PROPERTY(double loadProgress READ loadProgress NOTIFY loadProgressChanged)
    Q_PROPERTY(qint64 gaussianCount READ gaussianCount NOTIFY sceneChanged)
    Q_PROPERTY(int visibleGaussianCount READ visibleGaussianCount NOTIFY renderStatsChanged)
    Q_PROPERTY(double renderFps READ renderFps NOTIFY renderStatsChanged)
    Q_PROPERTY(double frameTimeMs READ frameTimeMs NOTIFY renderStatsChanged)
    Q_PROPERTY(double gpuTimeMs READ gpuTimeMs NOTIFY renderStatsChanged)
    Q_PROPERTY(double sortTimeMs READ sortTimeMs NOTIFY renderStatsChanged)
    Q_PROPERTY(double geometryUpdateFps READ geometryUpdateFps NOTIFY renderStatsChanged)
    Q_PROPERTY(int cameraRevisionLag READ cameraRevisionLag NOTIFY renderStatsChanged)
    Q_PROPERTY(double movementSpeed READ movementSpeed WRITE setMovementSpeed NOTIFY movementSpeedChanged)
    Q_PROPERTY(bool pathAvailable READ pathAvailable NOTIFY sceneChanged)
    Q_PROPERTY(bool followPath READ followPath WRITE setFollowPath NOTIFY navigationModeChanged)
    Q_PROPERTY(double pathProgress READ pathProgress NOTIFY pathProgressChanged)
    Q_PROPERTY(double captureEnvelopeScore READ captureEnvelopeScore NOTIFY captureEnvelopeChanged)
    Q_PROPERTY(QString captureEnvelopeStatus READ captureEnvelopeStatus NOTIFY captureEnvelopeChanged)
    Q_PROPERTY(int visualizationMode READ visualizationMode WRITE setVisualizationMode NOTIFY visualizationModeChanged)

public:
    explicit GaussianSplatView(QQuickItem *parent = nullptr);
    ~GaussianSplatView() override;

    QUrl source() const;
    void setSource(const QUrl &source);
    bool loading() const;
    bool ready() const;
    QString statusText() const;
    QString errorString() const;
    double loadProgress() const;
    qint64 gaussianCount() const;
    int visibleGaussianCount() const;
    double renderFps() const;
    double frameTimeMs() const;
    double gpuTimeMs() const;
    double sortTimeMs() const;
    double geometryUpdateFps() const;
    int cameraRevisionLag() const;
    double movementSpeed() const;
    void setMovementSpeed(double value);
    bool pathAvailable() const;
    bool followPath() const;
    void setFollowPath(bool value);
    double pathProgress() const;
    double captureEnvelopeScore() const;
    QString captureEnvelopeStatus() const;
    int visualizationMode() const;
    void setVisualizationMode(int value);

    Q_INVOKABLE void resetCamera();
    Q_INVOKABLE void look(double deltaX, double deltaY);
    Q_INVOKABLE void moveCamera(double forward, double right, double up, double elapsedSeconds);
    Q_INVOKABLE void changeMovementSpeed(double wheelSteps);

signals:
    void sourceChanged();
    void loadingChanged();
    void sceneChanged();
    void statusChanged();
    void loadProgressChanged();
    void renderStatsChanged();
    void movementSpeedChanged();
    void navigationModeChanged();
    void pathProgressChanged();
    void captureEnvelopeChanged();
    void visualizationModeChanged();

protected:
    QQuickRhiItemRenderer *createRenderer() override;

private:
    friend class GaussianSplatRenderer;

    std::shared_ptr<const GaussianSceneData> sceneData() const;
    QVector3D cameraPosition() const;
    QVector3D cameraForward() const;
    QVector3D cameraUp() const;
    float verticalFieldOfView() const;
    quint64 cameraRevision() const;
    void loadSource(const QString &path);
    void clearScene();
    void applyLoadedScene(std::shared_ptr<const GaussianSceneData> scene,
                          const QString &error,
                          quint64 generation);
    void reportRenderStats(int visibleCount,
                           double frameTimeMs,
                           double gpuTimeMs,
                           double sortTimeMs,
                           double framesPerSecond,
                           double geometryUpdatesPerSecond,
                           int cameraRevisionLag);
    void setStatus(const QString &status, const QString &error = {});
    void updateCameraVectors();
    void updatePathCamera();
    void updateCaptureEnvelope();

    QUrl m_source;
    std::shared_ptr<const GaussianSceneData> m_scene;
    QString m_statusText = QStringLiteral("No Gaussian world loaded");
    QString m_errorString;
    QVector3D m_cameraPosition { 0.0f, 0.0f, 2.0f };
    QVector3D m_cameraForward { 0.0f, 0.0f, -1.0f };
    QVector3D m_cameraUp { 0.0f, 1.0f, 0.0f };
    QVector3D m_initialPosition { 0.0f, 0.0f, 2.0f };
    QVector3D m_initialForward { 0.0f, 0.0f, -1.0f };
    QVector3D m_initialUp { 0.0f, 1.0f, 0.0f };
    QVector3D m_navigationUp { 0.0f, 1.0f, 0.0f };
    QVector3D m_baseForward { 0.0f, 0.0f, -1.0f };
    QVector3D m_baseUp { 0.0f, 1.0f, 0.0f };
    float m_yaw = 0.0f;
    float m_pitch = 0.0f;
    float m_verticalFieldOfView = 52.0f;
    double m_loadProgress = 0.0;
    double m_movementSpeed = 1.8;
    double m_renderFps = 0.0;
    double m_frameTimeMs = 0.0;
    double m_gpuTimeMs = 0.0;
    double m_sortTimeMs = 0.0;
    double m_geometryUpdateFps = 0.0;
    int m_visibleGaussianCount = 0;
    int m_cameraRevisionLag = 0;
    double m_pathDistance = 0.0;
    double m_pathLateralOffset = 0.0;
    double m_pathVerticalOffset = 0.0;
    double m_captureEnvelopeScore = 0.0;
    QString m_captureEnvelopeStatus = QStringLiteral("NO CAPTURE EVIDENCE");
    quint64 m_loadGeneration = 0;
    quint64 m_cameraRevision = 1;
    int m_visualizationMode = 0;
    bool m_loading = false;
    bool m_followPath = true;
};
