import QtQuick
import QtQuick.Layouts
import "."

Rectangle {
    id: root

    property string title: ""
    property string subtitle: ""
    property url iconSource: ""
    property url actionIcon: ""
    property string actionToolTip: ""
    signal actionTriggered()

    implicitHeight: Theme.panelHeaderHeight
    color: "transparent"

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 6
        spacing: 8

        SvgIcon {
            visible: root.iconSource.toString().length > 0
            source: root.iconSource
            iconSize: Theme.iconSm
            color: Theme.accentDim
        }

        Text {
            text: root.title
            color: Theme.text
            font.family: Theme.uiFont
            font.pixelSize: 11
            font.weight: Font.DemiBold
            font.letterSpacing: 0.3
        }

        Item {
            Layout.fillWidth: true
        }

        Text {
            visible: root.subtitle.length > 0
            text: root.subtitle
            color: Theme.textMuted
            font.family: Theme.uiFont
            font.pixelSize: 10
            elide: Text.ElideRight
            Layout.maximumWidth: 220
        }

        IconButton {
            visible: root.actionIcon.toString().length > 0
            iconSource: root.actionIcon
            toolTip: root.actionToolTip
            buttonSize: 24
            onClicked: root.actionTriggered()
        }
    }
}
