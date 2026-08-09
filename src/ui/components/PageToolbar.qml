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
    border.width: 1
    border.color: Theme.borderSoft

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 8
        spacing: 9

        SvgIcon {
            visible: root.iconSource.toString().length > 0
            source: root.iconSource
            iconSize: 16
        }

        Text {
            text: root.title
            color: Theme.text
            font.family: Theme.uiFont
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }

        Rectangle {
            visible: root.subtitle.length > 0
            Layout.preferredWidth: 1
            Layout.preferredHeight: 18
            color: Theme.border
        }

        Text {
            visible: root.subtitle.length > 0
            text: root.subtitle
            color: Theme.textMuted
            font.family: Theme.uiFont
            font.pixelSize: 10
            elide: Text.ElideRight
            Layout.maximumWidth: 560
        }

        Item { Layout.fillWidth: true }

        RowLayout {
            id: actionRow
            spacing: 6
        }
    }
}
