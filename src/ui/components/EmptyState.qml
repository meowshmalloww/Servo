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
        width: Math.min(420, Math.max(260, parent.width - 40))
        spacing: 11

        Item {
            id: tileWrap
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 44
            Layout.preferredHeight: 44

            Rectangle {
                id: tile
                anchors.fill: parent
                radius: 10
                color: Theme.panelRaised
                border.width: 1
                border.color: Theme.borderSoft
            }

            SvgIcon {
                anchors.centerIn: parent
                source: root.iconSource
                iconSize: Theme.iconXl
                color: Theme.textMuted
                opacity: 0.9
            }
        }

        Text {
            visible: root.title.length > 0
            text: root.title
            color: Theme.text
            font.family: Theme.uiFont
            font.pixelSize: 13
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
            lineHeight: 1.32
            Layout.fillWidth: true
        }

        TextButton {
            visible: root.actionText.length > 0
            text: root.actionText
            iconSource: root.actionIcon
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 4
            onClicked: root.actionRequested()
        }
    }
}
