import QtQuick
import QtQuick.Layouts
import "."

Rectangle {
    id: root

    property string title: ""
    property string subtitle: ""
    property url iconSource: ""
    default property alias actions: actionRow.data

    implicitHeight: Theme.toolbarHeight
    color: Theme.chrome

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 10
        spacing: 10

        SvgIcon {
            visible: root.iconSource.toString().length > 0
            source: root.iconSource
            iconSize: Theme.iconMd
            color: Theme.accent
        }

        Text {
            text: root.title
            color: Theme.text
            font.family: Theme.uiFont
            font.pixelSize: 13
            font.weight: Font.DemiBold
            font.letterSpacing: 0.2
        }

        Text {
            visible: root.subtitle.length > 0
            text: root.subtitle
            color: Theme.textMuted
            font.family: Theme.uiFont
            font.pixelSize: 10
            elide: Text.ElideRight
            Layout.maximumWidth: 560
            Layout.leftMargin: root.subtitle.length > 0 ? 2 : 0
        }

        Item {
            Layout.fillWidth: true
        }

        RowLayout {
            id: actionRow
            spacing: 6
        }
    }
}
