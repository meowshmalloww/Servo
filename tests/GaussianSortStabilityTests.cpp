#include <QFile>
#include <QTest>
#include <QVector3D>

#include <algorithm>
#include <bit>
#include <cmath>

namespace {

float viewDepth(const QVector3D &mean,
                const QVector3D &camera,
                const QVector3D &forward)
{
    return QVector3D::dotProduct(mean - camera, forward.normalized());
}

quint32 farToNearViewDepthKey(const QVector3D &mean,
                              const QVector3D &camera,
                              const QVector3D &forward)
{
    const float depth = viewDepth(mean, camera, forward);
    return ~std::bit_cast<quint32>(depth);
}

} // namespace

class GaussianSortStabilityTests final : public QObject
{
    Q_OBJECT

private slots:
    void viewDepthKeyIsFarToNear();
    void viewDepthOrderTracksTheProducingCamera();
    void preprocessShaderUsesTheTestedPolicy();
};

void GaussianSortStabilityTests::viewDepthKeyIsFarToNear()
{
    const QVector3D camera(0.0f, 0.0f, 0.0f);
    const QVector3D forward(0.0f, 0.0f, -1.0f);
    const quint32 nearKey = farToNearViewDepthKey(
        QVector3D(0.0f, 0.0f, -2.0f), camera, forward);
    const quint32 farKey = farToNearViewDepthKey(
        QVector3D(0.0f, 0.0f, -8.0f), camera, forward);

    QVERIFY2(farKey < nearKey,
             "Ascending radix order must remain back-to-front for premultiplied blending.");
}

void GaussianSortStabilityTests::viewDepthOrderTracksTheProducingCamera()
{
    const QVector3D camera(0.0f, 0.0f, 0.0f);
    const QVector3D first(1.0f, 0.0f, -4.0f);
    const QVector3D second(-1.0f, 0.0f, -5.0f);
    const QVector3D forwardA(0.0f, 0.0f, -1.0f);
    const QVector3D forwardB(std::sqrt(0.5f), 0.0f, -std::sqrt(0.5f));

    // View-space Z legitimately changes with the camera.  Servo must match the
    // gsplat 1.5.3 depth policy used to train and validate the artifact instead
    // of silently substituting an orientation-invariant radial order.
    QVERIFY(viewDepth(second, camera, forwardA) > viewDepth(first, camera, forwardA));
    QVERIFY(viewDepth(second, camera, forwardB) < viewDepth(first, camera, forwardB));

    const quint32 firstKeyBefore = farToNearViewDepthKey(first, camera, forwardA);
    const quint32 secondKeyBefore = farToNearViewDepthKey(second, camera, forwardA);
    const quint32 firstKeyAfter = farToNearViewDepthKey(first, camera, forwardB);
    const quint32 secondKeyAfter = farToNearViewDepthKey(second, camera, forwardB);
    QVERIFY(firstKeyAfter != firstKeyBefore);
    QVERIFY(secondKeyAfter != secondKeyBefore);
    QVERIFY(secondKeyBefore < firstKeyBefore);
    QVERIFY(firstKeyAfter < secondKeyAfter);
}

void GaussianSortStabilityTests::preprocessShaderUsesTheTestedPolicy()
{
    QFile shader(QStringLiteral(SERVO_GAUSSIAN_PREPROCESS_SHADER));
    QVERIFY2(shader.open(QIODevice::ReadOnly | QIODevice::Text),
             qPrintable(shader.errorString()));
    const QByteArray source = shader.readAll();

    QVERIFY(source.contains("depthKeys[index] = ~floatBitsToUint(depth);"));
    QVERIFY(!source.contains("depthKeys[index] = ~floatBitsToUint(cameraDistanceSquared);"));
}

QTEST_GUILESS_MAIN(GaussianSortStabilityTests)
#include "GaussianSortStabilityTests.moc"
