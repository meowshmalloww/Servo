import QtQuick
import QtQuick.Layouts
import "."

Rectangle {
    id: root

    signal addFilesRequested
    signal addFolderRequested
    signal urlsDropped(var urls)

    property bool acceptingDrop: dropArea.containsDrag

    implicitHeight: 176
    color: acceptingDrop ? Theme.selection : Theme.field
    border.width: acceptingDrop ? 2 : 1
    border.color: acceptingDrop ? Theme.selectionBorder : Theme.borderStrong
    radius: Theme.cornerControl

    DropArea {
        id: dropArea
        anchors.fill: parent

        onDropped: function(drop) {
            if (!drop.hasUrls)
                return;
            root.urlsDropped(drop.urls);
            drop.acceptProposedAction();
        }
    }

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 40, 560)
        spacing: 8

        SvgIcon {
            source: Theme.icon("open")
            iconSize: 30
            Layout.alignment: Qt.AlignHCenter
            opacity: root.acceptingDrop ? 1 : 0.78
        }

        Text {
            Layout.fillWidth: true
            text: root.acceptingDrop
                  ? "Release to add these sources"
                  : "Drop images, videos, or folders here"
            color: Theme.text
            font.family: Theme.uiFont
            font.pixelSize: 15
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
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
