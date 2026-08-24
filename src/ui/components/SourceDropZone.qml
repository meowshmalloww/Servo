import QtQuick
import QtQuick.Layouts
import "."

Rectangle {
    id: root

    signal addFilesRequested
    signal addFolderRequested
    signal urlsDropped(var urls)

    property bool acceptingDrop: dropArea.containsDrag

    implicitHeight: 172
    radius: Theme.cornerCard + 2
    color: acceptingDrop ? Theme.selection : Theme.field

    Behavior on color {
        ColorAnimation {
            duration: Theme.animBase
            easing.type: Easing.OutCubic
        }
    }

    DropArea {
        id: dropArea
        anchors.fill: parent

        onDropped: function (drop) {
            if (!drop.hasUrls)
                return;
            root.urlsDropped(drop.urls);
            drop.acceptProposedAction();
        }
    }

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 560)
        spacing: 10

        Item {
            id: tileWrap
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 46
            Layout.preferredHeight: 46

            Rectangle {
                anchors.fill: parent
                radius: Theme.cornerCard
                color: root.acceptingDrop ? Theme.accent : Theme.panelRaised

                Behavior on color {
                    ColorAnimation {
                        duration: Theme.animBase
                    }
                }
            }

            SvgIcon {
                id: tileIcon
                anchors.centerIn: parent
                source: Theme.icon("open")
                iconSize: 19
                color: root.acceptingDrop ? Theme.accentText : Theme.textSecondary
                scale: root.acceptingDrop ? 1.12 : 1.0

                Behavior on color {
                    ColorAnimation {
                        duration: Theme.animBase
                    }
                }

                Behavior on scale {
                    NumberAnimation {
                        duration: Theme.animMove
                        easing.type: Easing.OutBack
                    }
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: root.acceptingDrop ? "Release to add these sources" : "Drop images, videos, or folders here"
            color: root.acceptingDrop ? Theme.text : Theme.textSecondary
            font.family: Theme.uiFont
            font.pixelSize: 14
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter

            Behavior on color {
                ColorAnimation {
                    duration: Theme.animBase
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: "Original media stays in place. Servo reads headers in the background and does not copy or fully decode files during import."
            color: Theme.textMuted
            font.family: Theme.uiFont
            font.pixelSize: 10
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
        }

        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 2
            spacing: 7

            TextButton {
                text: "Add files"
                iconSource: Theme.icon("plus")
                tone: "primary"
                onClicked: root.addFilesRequested()
            }

            TextButton {
                text: "Add folder"
                iconSource: Theme.icon("folder")
                onClicked: root.addFolderRequested()
            }
        }
    }
}
