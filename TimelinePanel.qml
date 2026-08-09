import QtQuick
import QtQuick.Layouts

PanelFrame {
    id: root

    property real position: 0.414
    property bool running: false
    property real durationSeconds: 30
    signal seekRequested(real position)
    signal runningToggled

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            color: Theme.chrome
            border.width: 1
            border.color: Theme.border
            Layout.fillWidth: true
            Layout.preferredHeight: 39

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                spacing: 5

                IconButton { glyph: "|◀"; toolTip: "First frame" }
                IconButton { glyph: "◀"; toolTip: "Step back" }
                IconButton {
                    glyph: root.running ? "Ⅱ" : "▶"
                    toolTip: root.running ? "Pause" : "Play"
                    selected: root.running
                    onClicked: root.runningToggled()
                }
                IconButton { glyph: "▶"; toolTip: "Step forward" }
                IconButton { glyph: "▶|"; toolTip: "Last frame" }

                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 20; color: Theme.border }

                Text {
                    text: formatTime(root.position * root.durationSeconds)
                    color: Theme.text
                    font.family: Theme.monoFont
                    font.pixelSize: 11
                }

                Item { Layout.fillWidth: true }

                Text {
                    text: "Frame  " + Math.round(root.position * 1249) + " / 1249"
                    color: Theme.textSecondary
                    font.family: Theme.monoFont
                    font.pixelSize: 10
                }

                AppButton { text: "1.0×"; compact: true }
                IconButton { glyph: "⛶"; toolTip: "Expand timeline" }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 34

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: "0 s"
                color: Theme.textMuted
                font.family: Theme.monoFont
                font.pixelSize: 9
            }

            Text {
                anchors.right: parent.right
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: "30 s"
                color: Theme.textMuted
                font.family: Theme.monoFont
                font.pixelSize: 9
            }

            Rectangle {
                id: ruler
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 44
                anchors.rightMargin: 44
                anchors.verticalCenter: parent.verticalCenter
                height: 3
                color: Theme.borderStrong

                Rectangle {
                    width: parent.width * root.position
                    height: parent.height
                    color: Theme.accent
                }

                Rectangle {
                    x: parent.width * root.position - 1
                    y: -7
                    width: 2
                    height: 17
                    color: Theme.text
                }

                MouseArea {
                    anchors.fill: parent
                    anchors.topMargin: -10
                    anchors.bottomMargin: -10
                    cursorShape: Qt.PointingHandCursor
                    onPressed: mouse => root.seekRequested(Math.max(0, Math.min(1, mouse.x / width)))
                    onPositionChanged: mouse => {
                        if (pressed)
                            root.seekRequested(Math.max(0, Math.min(1, mouse.x / width)))
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 8
            Layout.rightMargin: 8
            Layout.bottomMargin: 7
            spacing: 3

            Repeater {
                model: [
                    { name: "Camera", color: Theme.textMuted, start: 0.00, length: 1.00 },
                    { name: "Detection", color: Theme.teal, start: 0.04, length: 0.72 },
                    { name: "Planner", color: Theme.yellow, start: 0.28, length: 0.68 },
                    { name: "Control", color: Theme.red, start: 0.43, length: 0.48 }
                ]

                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 8

                    Text {
                        text: modelData.name
                        color: Theme.textSecondary
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        Layout.preferredWidth: 68
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        color: Theme.field
                        border.width: 1
                        border.color: Theme.border

                        Rectangle {
                            x: parent.width * modelData.start
                            width: parent.width * modelData.length
                            height: Math.max(3, parent.height - 6)
                            anchors.verticalCenter: parent.verticalCenter
                            color: Theme.tint(modelData.color, 0.72)
                        }

                        Rectangle {
                            x: parent.width * root.position - 1
                            width: 2
                            height: parent.height
                            color: Theme.text
                        }
                    }
                }
            }
        }
    }

    function formatTime(seconds) {
        const mins = Math.floor(seconds / 60)
        const secs = seconds - mins * 60
        return String(mins).padStart(2, "0") + ":" + secs.toFixed(2).padStart(5, "0")
    }
}
