import QtQuick
import QtQuick.Layouts

PanelFrame {
    id: root

    property url imageSource: Qt.resolvedUrl("docs/ui-redesign-v2/02-simulate-workspace.png")
    property rect clipRect: Qt.rect(275, 112, 956, 590)
    property string cameraName: "Front camera"
    property string trackedObjectName: "Pedestrian_03"
    property string objectMetric: "confidence 0.28"
    property bool showDetection: true
    property bool showTrajectory: true
    property bool candidate: false
    property bool interactive: true
    signal objectSelected

    color: "#050607"
    clip: true

    Image {
        id: sceneImage
        anchors.fill: parent
        anchors.margins: 1
        source: root.imageSource
        sourceClipRect: root.clipRect
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: true
        smooth: true
    }

    Rectangle {
        anchors.fill: sceneImage
        color: "#000000"
        opacity: 0.09
    }

    Canvas {
        anchors.fill: parent
        visible: root.showTrajectory
        antialiasing: true

        onPaint: {
            const ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            ctx.strokeStyle = root.candidate ? Theme.green : Theme.accentBright
            ctx.lineWidth = 2.5
            ctx.setLineDash([9, 7])
            ctx.beginPath()
            ctx.moveTo(width * 0.51, height * 0.92)
            ctx.bezierCurveTo(width * 0.50, height * 0.72,
                              width * 0.52, height * 0.56,
                              width * 0.45, height * 0.43)
            ctx.stroke()
            ctx.setLineDash([])
        }
    }

    Rectangle {
        id: detectionBox
        visible: root.showDetection
        x: root.width * 0.39
        y: root.height * 0.39
        width: Math.max(38, root.width * 0.055)
        height: Math.max(84, root.height * 0.25)
        color: "transparent"
        border.width: 2
        border.color: root.candidate ? Theme.green : Theme.accentBright

        Rectangle {
            anchors.left: parent.left
            anchors.bottom: parent.top
            height: 22
            width: objectText.implicitWidth + 12
            color: Theme.tint(root.candidate ? Theme.green : Theme.accent, 0.88)

            Text {
                id: objectText
                anchors.centerIn: parent
                text: root.trackedObjectName + "  ·  " + root.objectMetric
                color: "#0a0c0e"
                font.family: Theme.uiFont
                font.pixelSize: 10
                font.weight: Font.DemiBold
            }
        }

        MouseArea {
            anchors.fill: parent
            enabled: root.interactive
            cursorShape: Qt.PointingHandCursor
            onClicked: root.objectSelected()
        }
    }

    RowLayout {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 10
        spacing: 5

        AppButton {
            text: root.cameraName
            glyph: "▣"
            compact: true
        }

        AppButton {
            text: "Overlays"
            glyph: "◇"
            compact: true
        }
    }

    Row {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 10
        spacing: 4

        IconButton { glyph: "⌖"; toolTip: "Focus selection" }
        IconButton { glyph: "✥"; toolTip: "Move tool" }
        IconButton { glyph: "▦"; toolTip: "Viewport layout" }
        IconButton { glyph: "⛶"; toolTip: "Maximize viewport" }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 10
        width: legendColumn.implicitWidth + 20
        height: legendColumn.implicitHeight + 16
        color: Theme.tint(Theme.window, 0.86)
        border.width: 1
        border.color: Theme.borderStrong

        Column {
            id: legendColumn
            anchors.centerIn: parent
            spacing: 6

            Repeater {
                model: [
                    { label: "Planned trajectory", color: root.candidate ? Theme.green : Theme.accentBright },
                    { label: "Detected object", color: Theme.teal },
                    { label: "Brake event", color: Theme.red }
                ]

                delegate: Row {
                    required property var modelData
                    spacing: 7

                    Rectangle {
                        width: 18
                        height: 2
                        anchors.verticalCenter: parent.verticalCenter
                        color: modelData.color
                    }

                    Text {
                        text: modelData.label
                        color: Theme.textSecondary
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                }
            }
        }
    }

    Rectangle {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 10
        width: fpsLabel.implicitWidth + 12
        height: 22
        color: Theme.tint(Theme.window, 0.8)
        border.width: 1
        border.color: Theme.border

        Text {
            id: fpsLabel
            anchors.centerIn: parent
            text: root.candidate ? "candidate · 58 FPS" : "baseline · 58 FPS"
            color: Theme.green
            font.family: Theme.monoFont
            font.pixelSize: 10
        }
    }
}
