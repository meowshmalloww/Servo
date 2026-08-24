import QtQuick
import QtQuick.Layouts
import "."

Item {
    id: root

    property url iconSource: Theme.icon("info")
    property string title: "No data"
    property string description: ""
    property string actionText: ""
    property url actionIcon: ""
    signal actionRequested()

    implicitWidth: content.implicitWidth
    implicitHeight: content.implicitHeight

    ColumnLayout {
        id: content
        anchors.centerIn: parent
        width: Math.min(380, Math.max(240, parent.width - 40))
        spacing: 10

        Item {
            id: tileWrap
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 42
            Layout.preferredHeight: 42

            Rectangle {
                id: tile
                anchors.fill: parent
                radius: Theme.cornerCard + 2
                color: Theme.selection
                opacity: 0.55
            }

            SvgIcon {
                anchors.centerIn: parent
                source: root.iconSource
                iconSize: Theme.iconXl
                color: Theme.accentDim
                opacity: 0.95
            }
        }

        Text {
            visible: root.title.length > 0
            text: root.title
            color: Theme.textSecondary
            font.family: Theme.uiFont
            font.pixelSize: 12
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
        }

        Text {
            visible: root.description.length > 0
            text: root.description
            color: Theme.textMuted
            font.family: Theme.uiFont
            font.pixelSize: 10
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            lineHeight: 1.25
            Layout.fillWidth: true
        }

        TextButton {
            visible: root.actionText.length > 0
            text: root.actionText
            iconSource: root.actionIcon
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 3
            onClicked: root.actionRequested()
        }
    }
}
