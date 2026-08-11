#include "GaussianPathSmoothing.h"

#include <algorithm>
#include <cmath>
#include <vector>

namespace {

float median(std::vector<float> values)
{
    if (values.empty())
        return 0.0f;
    const auto middle = values.begin() + std::ptrdiff_t(values.size() / 2);
    std::nth_element(values.begin(), middle, values.end());
    const float upper = *middle;
    if (values.size() % 2 != 0)
        return upper;
    const float lower = *std::max_element(values.begin(), middle);
    return 0.5f * (lower + upper);
}

QVector3D normalizedOr(const QVector3D &value, const QVector3D &fallback)
{
    const float lengthSquared = value.lengthSquared();
    return std::isfinite(lengthSquared) && lengthSquared > 1e-10f
               ? value / std::sqrt(lengthSquared)
               : fallback;
}

} // namespace

QVector<QVector3D> Servo::smoothNavigationHeights(const QVector<QVector3D> &path,
                                                   const QVector3D &navigationUp,
                                                   qsizetype radius)
{
    if (path.size() < 3 || radius < 1)
        return path;

    const QVector3D up = normalizedOr(navigationUp, QVector3D(0.0f, 1.0f, 0.0f));
    QVector<float> distances(path.size(), 0.0f);
    QVector<float> heights(path.size(), 0.0f);
    std::vector<float> steps;
    steps.reserve(size_t(path.size() - 1));
    for (qsizetype index = 0; index < path.size(); ++index) {
        heights[index] = QVector3D::dotProduct(path.at(index), up);
        if (index == 0)
            continue;
        const float step = (path.at(index) - path.at(index - 1)).length();
        distances[index] = distances[index - 1]
                           + (std::isfinite(step) ? std::max(step, 0.0f) : 0.0f);
        if (std::isfinite(step) && step > 1e-6f)
            steps.push_back(step);
    }
    if (steps.empty())
        return path;

    const float maximumCorrection = std::max(1e-5f, 1.5f * median(steps));
    QVector<QVector3D> result = path;
    for (qsizetype index = 0; index < path.size(); ++index) {
        const qsizetype first = std::max<qsizetype>(0, index - radius);
        const qsizetype last = std::min<qsizetype>(path.size() - 1, index + radius);
        const qsizetype sampleCount = last - first + 1;
        std::vector<double> weights(size_t(sampleCount), 1.0);
        double slope = 0.0;
        double intercept = double(heights[index]);
        // Iteratively reweighted local linear regression preserves a genuine
        // incline exactly, averages periodic handheld bounce, and limits the
        // influence of an isolated bad SfM pose.
        for (int iteration = 0; iteration < 3; ++iteration) {
            double weightSum = 0.0;
            double distanceMean = 0.0;
            double heightMean = 0.0;
            for (qsizetype sample = first; sample <= last; ++sample) {
                const double weight = weights[size_t(sample - first)];
                weightSum += weight;
                distanceMean += weight * double(distances[sample]);
                heightMean += weight * double(heights[sample]);
            }
            if (weightSum <= 1e-12)
                break;
            distanceMean /= weightSum;
            heightMean /= weightSum;
            double covariance = 0.0;
            double variance = 0.0;
            for (qsizetype sample = first; sample <= last; ++sample) {
                const double weight = weights[size_t(sample - first)];
                const double centered = double(distances[sample]) - distanceMean;
                covariance += weight * centered
                              * (double(heights[sample]) - heightMean);
                variance += weight * centered * centered;
            }
            slope = variance > 1e-12 ? covariance / variance : 0.0;
            intercept = heightMean - slope * distanceMean;
            std::vector<float> absoluteResiduals;
            absoluteResiduals.reserve(size_t(sampleCount));
            for (qsizetype sample = first; sample <= last; ++sample) {
                const double residual = double(heights[sample])
                                        - (intercept + slope * double(distances[sample]));
                absoluteResiduals.push_back(float(std::abs(residual)));
            }
            const double robustScale = std::max(1e-6,
                                                1.4826 * double(median(absoluteResiduals)));
            const double huberLimit = 1.5 * robustScale;
            for (qsizetype sample = first; sample <= last; ++sample) {
                const double residual = std::abs(double(heights[sample])
                                                 - (intercept
                                                    + slope * double(distances[sample])));
                weights[size_t(sample - first)] = residual <= huberLimit
                                                      ? 1.0
                                                      : huberLimit / residual;
            }
        }
        const float predicted = float(intercept + slope * double(distances[index]));
        const float correction = std::clamp(predicted - heights[index],
                                            -maximumCorrection,
                                            maximumCorrection);
        result[index] += up * correction;
    }
    return result;
}
