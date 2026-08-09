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
    color: Theme.chrome
    border.width: 1
    border.color: Theme.borderSoft

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 5
        spacing: 7

        SvgIcon {
            visible: root.iconSource.toString().length > 0
            source: root.iconSource
            iconSize: 14
        }

        Text {
            text: root.title
            color: Theme.text
            font.family: Theme.uiFont
            font.pixelSize: 11
            font.weight: Font.DemiBold
        }

        Item { Layout.fillWidth: true }

        Text {
            visible: root.subtitle.length > 0
            text: root.subtitle
            color: Theme.textMuted
            font.family: Theme.uiFont
            font.pixelSize: 10
            elide: Text.ElideRight
            Layout.maximumWidth: 180
        }

        IconButton {
            visible: root.actionIcon.toString().length > 0
            iconSource: root.actionIcon
            toolTip: root.actionToolTip
            buttonSize: 25
            onClicked: root.actionTriggered()
        }
    }
}
