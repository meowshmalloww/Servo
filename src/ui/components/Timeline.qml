import QtQuick
import QtQuick.Layouts
import "."

Panel {
    id: root

    property bool available: false
    property real position: 0
    signal playRequested()
    signal stopRequested()
    signal seekRequested(real position)

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 34
            color: Theme.chrome
            border.width: 1
            border.color: Theme.borderSoft

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 7
                anchors.rightMargin: 9
                spacing: 4

                IconButton {
                    iconSource: Theme.icon("play")
                    toolTip: "Play"
                    enabled: root.available
                    onClicked: root.playRequested()
                }

                IconButton {
                    iconSource: Theme.icon("stop")
                    toolTip: "Stop"
                    enabled: root.available
                    onClicked: root.stopRequested()
                }

                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 18; color: Theme.border }

                Text {
                    text: root.available ? "00:00:00.000" : "No run selected"
                    color: root.available ? Theme.textSecondary : Theme.textMuted
                    font.family: Theme.monoFont
                    font.pixelSize: 10
                }

                Item { Layout.fillWidth: true }

                Text {
                    text: root.available ? "Frame 0 / 0" : ""
                    color: Theme.textMuted
                    font.family: Theme.monoFont
                    font.pixelSize: 9
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            opacity: root.available ? 1 : 0.45

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                height: 2
                color: Theme.borderStrong

                Rectangle {
                    width: parent.width * root.position
                    height: parent.height
                    color: Theme.accent
                }
            }

            MouseArea {
                anchors.fill: parent
                enabled: root.available
                cursorShape: Qt.PointingHandCursor
                onClicked: mouse => root.seekRequested(Math.max(0, Math.min(1, mouse.x / width)))
            }
        }
    }
}
