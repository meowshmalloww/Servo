import QtQuick
import QtQuick.Layouts

PanelFrame {
    id: root

    property string title: "Metric"
    property string value: ""
    property string unit: ""
    property color lineColor: Theme.teal
    property color secondLineColor: Theme.accent
    property var values: [0.62, 0.59, 0.55, 0.48, 0.42, 0.31, 0.24]
    property var secondValues: []
    property real minimum: 0
    property real maximum: 1
    property string xStart: "0"
    property string xEnd: "12"

    onValuesChanged: plot.requestPaint()
    onSecondValuesChanged: plot.requestPaint()
    onMinimumChanged: plot.requestPaint()
    onMaximumChanged: plot.requestPaint()
    onWidthChanged: plot.requestPaint()
    onHeightChanged: plot.requestPaint()

    RowLayout {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        height: 34

        Text {
            text: root.title
            color: Theme.textSecondary
            font.family: Theme.uiFont
            font.pixelSize: 11
            font.weight: Font.DemiBold
            Layout.fillWidth: true
        }

        Text {
            visible: root.value.length > 0
            text: root.value
            color: root.lineColor
            font.family: Theme.monoFont
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }

        Text {
            visible: root.unit.length > 0
            text: root.unit
            color: Theme.textMuted
            font.family: Theme.uiFont
            font.pixelSize: 10
        }
    }

    Canvas {
        id: plot
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        anchors.topMargin: 36
        anchors.bottomMargin: 20
        antialiasing: true

        onPaint: {
            const ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)

            ctx.strokeStyle = Theme.border
            ctx.lineWidth = 1
            for (let i = 0; i <= 4; ++i) {
                const y = Math.round(i * height / 4) + 0.5
                ctx.beginPath()
                ctx.moveTo(0, y)
                ctx.lineTo(width, y)
                ctx.stroke()
            }

            drawSeries(ctx, root.values, root.lineColor)
            if (root.secondValues && root.secondValues.length > 1)
                drawSeries(ctx, root.secondValues, root.secondLineColor)
        }

        function drawSeries(ctx, series, color) {
            if (!series || series.length < 2)
                return

            const span = Math.max(0.0001, root.maximum - root.minimum)
            ctx.strokeStyle = color
            ctx.lineWidth = 1.5
            ctx.lineJoin = "round"
            ctx.beginPath()
            for (let i = 0; i < series.length; ++i) {
                const x = i * width / (series.length - 1)
                const normalized = Math.max(0, Math.min(1, (series[i] - root.minimum) / span))
                const y = height - normalized * height
                if (i === 0)
                    ctx.moveTo(x, y)
                else
                    ctx.lineTo(x, y)
            }
            ctx.stroke()
        }
    }

    Text {
        anchors.left: parent.left
        anchors.leftMargin: 10
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 4
        text: root.xStart
        color: Theme.textMuted
        font.family: Theme.monoFont
        font.pixelSize: 9
    }

    Text {
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 4
        text: root.xEnd
        color: Theme.textMuted
        font.family: Theme.monoFont
        font.pixelSize: 9
    }
}
