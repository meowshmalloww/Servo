#include "GaussianPathSmoothing.h"

#include <QTest>

#include <cmath>

class GaussianPathSmoothingTests final : public QObject
{
    Q_OBJECT

private slots:
    void preservesSustainedGrade();
    void suppressesHighFrequencyHeightBounce();
    void rejectsBounceAndOutlierWhilePreservingRotatedGrade();
};

void GaussianPathSmoothingTests::preservesSustainedGrade()
{
    QVector<QVector3D> path;
    for (int index = 0; index < 20; ++index)
        path.append(QVector3D(float(index), 0.075f * float(index), 0.0f));

    const QVector<QVector3D> smoothed = Servo::smoothNavigationHeights(
        path, QVector3D(0.0f, 1.0f, 0.0f));
    QCOMPARE(smoothed.size(), path.size());
    for (qsizetype index = 0; index < path.size(); ++index) {
        QVERIFY(qAbs(smoothed[index].x() - path[index].x()) < 1e-6f);
        QVERIFY(qAbs(smoothed[index].y() - path[index].y()) < 1e-5f);
        QVERIFY(qAbs(smoothed[index].z() - path[index].z()) < 1e-6f);
    }
}

void GaussianPathSmoothingTests::suppressesHighFrequencyHeightBounce()
{
    QVector<QVector3D> path;
    double rawError = 0.0;
    for (int index = 0; index < 25; ++index) {
        const float expected = 0.04f * float(index);
        const float bounce = index % 2 == 0 ? 0.18f : -0.18f;
        path.append(QVector3D(float(index), expected + bounce, 0.0f));
        rawError += qAbs(bounce);
    }

    const QVector<QVector3D> smoothed = Servo::smoothNavigationHeights(
        path, QVector3D(0.0f, 1.0f, 0.0f));
    double smoothedError = 0.0;
    for (qsizetype index = 0; index < smoothed.size(); ++index) {
        const float expected = 0.04f * float(index);
        smoothedError += qAbs(smoothed[index].y() - expected);
        QVERIFY(qAbs(smoothed[index].x() - path[index].x()) < 1e-6f);
        QVERIFY(qAbs(smoothed[index].z() - path[index].z()) < 1e-6f);
    }
    QVERIFY2(smoothedError < rawError * 0.45,
             "Robust path smoothing must materially reduce vertical pose bounce.");
}

void GaussianPathSmoothingTests::rejectsBounceAndOutlierWhilePreservingRotatedGrade()
{
    const QVector3D up = QVector3D(0.35f, 0.82f, -0.45f).normalized();
    const QVector3D horizontal = QVector3D::crossProduct(up, QVector3D(0.0f, 0.0f, 1.0f))
                                     .normalized();
    QVector<QVector3D> path;
    QVector<float> expectedHeights;
    double rawSquaredError = 0.0;
    for (int index = 0; index < 41; ++index) {
        const float expected = index < 10
                                   ? 0.0f
                                   : (index <= 30 ? 0.08f * float(index - 9)
                                                  : 0.08f * 21.0f);
        const float bounce = index % 2 == 0 ? 0.25f : -0.25f;
        const float outlier = index == 20 ? 1.2f : 0.0f;
        expectedHeights.append(expected);
        path.append(horizontal * float(index) + up * (expected + bounce + outlier));
        rawSquaredError += double(bounce + outlier) * double(bounce + outlier);
    }

    const QVector<QVector3D> smoothed = Servo::smoothNavigationHeights(path, up);
    double smoothedSquaredError = 0.0;
    for (qsizetype index = 0; index < path.size(); ++index) {
        const QVector3D rawPerpendicular = path[index]
                                           - up * QVector3D::dotProduct(path[index], up);
        const QVector3D smoothPerpendicular = smoothed[index]
                                              - up * QVector3D::dotProduct(smoothed[index], up);
        QVERIFY((smoothPerpendicular - rawPerpendicular).length() < 1e-5f);
        const double residual = QVector3D::dotProduct(smoothed[index], up)
                                - expectedHeights[index];
        smoothedSquaredError += residual * residual;
    }
    const double rmsRatio = std::sqrt(smoothedSquaredError / rawSquaredError);
    QVERIFY(rmsRatio <= 0.30);
    const float firstHeight = QVector3D::dotProduct(smoothed.first(), up);
    const float lastHeight = QVector3D::dotProduct(smoothed.last(), up);
    const float expectedClimb = expectedHeights.last() - expectedHeights.first();
    QVERIFY(qAbs((lastHeight - firstHeight) - expectedClimb) <= 0.02f);
    const float recoveredGrade = (
        QVector3D::dotProduct(smoothed[30], up)
        - QVector3D::dotProduct(smoothed[10], up)
    ) / 20.0f;
    QVERIFY(qAbs(recoveredGrade - 0.08f) / 0.08f <= 0.15f);
    QVERIFY(qAbs(QVector3D::dotProduct(smoothed[20], up) - expectedHeights[20]) <= 0.25f);
}

QTEST_GUILESS_MAIN(GaussianPathSmoothingTests)
#include "GaussianPathSmoothingTests.moc"
