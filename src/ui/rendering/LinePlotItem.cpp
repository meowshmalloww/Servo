#include "LinePlotItem.h"

#include <QSGFlatColorMaterial>
#include <QSGGeometryNode>
#include <algorithm>

LinePlotItem::LinePlotItem(QQuickItem *parent)
    : QQuickItem(parent)
{
    setFlag(ItemHasContents, true);
}

QVariantList LinePlotItem::values() const
{
    return m_values;
}

void LinePlotItem::setValues(const QVariantList &values)
{
    if (m_values == values)
        return;
    m_values = values;
    emit valuesChanged();
    update();
}

QColor LinePlotItem::lineColor() const
{
    return m_lineColor;
}

void LinePlotItem::setLineColor(const QColor &color)
{
    if (m_lineColor == color)
        return;
    m_lineColor = color;
    emit lineColorChanged();
    update();
}

qreal LinePlotItem::minimum() const
{
    return m_minimum;
}

void LinePlotItem::setMinimum(qreal minimum)
{
    if (qFuzzyCompare(m_minimum, minimum))
        return;
    m_minimum = minimum;
    emit rangeChanged();
    update();
}

qreal LinePlotItem::maximum() const
{
    return m_maximum;
}

void LinePlotItem::setMaximum(qreal maximum)
{
    if (qFuzzyCompare(m_maximum, maximum))
        return;
    m_maximum = maximum;
    emit rangeChanged();
    update();
}

QSGNode *LinePlotItem::updatePaintNode(QSGNode *oldNode, UpdatePaintNodeData *)
{
    if (m_values.size() < 2 || width() <= 0 || height() <= 0 || m_maximum <= m_minimum) {
        delete oldNode;
        return nullptr;
    }

    auto *node = static_cast<QSGGeometryNode *>(oldNode);
    if (!node) {
        node = new QSGGeometryNode;
        auto *geometry = new QSGGeometry(QSGGeometry::defaultAttributes_Point2D(), m_values.size());
        geometry->setDrawingMode(QSGGeometry::DrawLineStrip);
        geometry->setLineWidth(1.0f);
        node->setGeometry(geometry);
        node->setFlag(QSGNode::OwnsGeometry);

        auto *material = new QSGFlatColorMaterial;
        node->setMaterial(material);
        node->setFlag(QSGNode::OwnsMaterial);
    }

    QSGGeometry *geometry = node->geometry();
    geometry->allocate(m_values.size());
    auto *vertices = geometry->vertexDataAsPoint2D();
    const qreal span = m_maximum - m_minimum;
    const int last = m_values.size() - 1;

    for (int index = 0; index < m_values.size(); ++index) {
        const qreal value = std::clamp(m_values.at(index).toDouble(), m_minimum, m_maximum);
        const float x = static_cast<float>((static_cast<qreal>(index) / last) * width());
        const float y = static_cast<float>(height() - ((value - m_minimum) / span) * height());
        vertices[index].set(x, y);
    }

    auto *material = static_cast<QSGFlatColorMaterial *>(node->material());
    material->setColor(m_lineColor);
    node->markDirty(QSGNode::DirtyGeometry | QSGNode::DirtyMaterial);
    return node;
}
