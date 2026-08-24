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

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 16
                    color: Theme.borderSoft
                }

                Text {
                    text: root.available ? "00:00:00.000" : "No run selected"
                    color: root.available ? Theme.textSecondary : Theme.textMuted
                    font.family: Theme.monoFont
                    font.pixelSize: 10
                }

                Item {
                    Layout.fillWidth: true
                }

                Text {
                    text: root.available ? "Frame 0 / 0" : ""
                    color: Theme.textMuted
                    font.family: Theme.monoFont
                    font.pixelSize: 9
                }
            }
        }

        Item {
            id: trackArea
            Layout.fillWidth: true
            Layout.fillHeight: true
            opacity: root.available ? 1 : 0.4

            Behavior on opacity {
                NumberAnimation {
                    duration: Theme.animBase
                }
            }

            Rectangle {
                id: track
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                height: trackHover.hovered ? 5 : 3
                radius: height / 2
                color: Theme.panelHover

                Behavior on height {
                    NumberAnimation {
                        duration: Theme.animFast
                        easing.type: Easing.OutCubic
                    }
                }

                Rectangle {
                    width: parent.width * root.position
                    height: parent.height
                    radius: parent.radius
                    color: Theme.accent

                    Behavior on width {
                        NumberAnimation {
                            duration: Theme.animFast
                            easing.type: Easing.OutCubic
                        }
                    }
                }
            }

            HoverHandler {
                id: trackHover
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
