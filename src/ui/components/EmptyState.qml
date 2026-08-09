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
        width: Math.min(360, Math.max(220, parent.width - 36))
        spacing: 8

        SvgIcon {
            source: root.iconSource
            iconSize: 28
            opacity: 0.65
            Layout.alignment: Qt.AlignHCenter
        }

        Text {
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
            lineHeight: 1.2
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
