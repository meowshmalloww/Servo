#pragma once

#include <QColor>
#include <QQuickItem>
#include <QVariantList>
#include <qqmlintegration.h>

class LinePlotItem : public QQuickItem
{
    Q_OBJECT
    QML_ELEMENT

    Q_PROPERTY(QVariantList values READ values WRITE setValues NOTIFY valuesChanged)
    Q_PROPERTY(QColor lineColor READ lineColor WRITE setLineColor NOTIFY lineColorChanged)
    Q_PROPERTY(qreal minimum READ minimum WRITE setMinimum NOTIFY rangeChanged)
    Q_PROPERTY(qreal maximum READ maximum WRITE setMaximum NOTIFY rangeChanged)

public:
    explicit LinePlotItem(QQuickItem *parent = nullptr);

    QVariantList values() const;
    void setValues(const QVariantList &values);

    QColor lineColor() const;
    void setLineColor(const QColor &color);

    qreal minimum() const;
    void setMinimum(qreal minimum);

    qreal maximum() const;
    void setMaximum(qreal maximum);

signals:
    void valuesChanged();
    void lineColorChanged();
    void rangeChanged();

protected:
    QSGNode *updatePaintNode(QSGNode *oldNode, UpdatePaintNodeData *) override;

private:
    QVariantList m_values;
    QColor m_lineColor = QColor(QStringLiteral("#86a9cc"));
    qreal m_minimum = 0.0;
    qreal m_maximum = 1.0;
};
