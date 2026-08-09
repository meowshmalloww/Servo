import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import "."

Item {
    id: root

    property string label: ""
    property string value: "--"
    property string toolTip: ""

    implicitWidth: row.implicitWidth
    implicitHeight: 26

    RowLayout {
        id: row
        anchors.centerIn: parent
        spacing: 5

        Text {
            text: root.label
            color: Theme.textMuted
            font.family: Theme.uiFont
            font.pixelSize: 9
        }

        Text {
            text: root.value
            color: Theme.textSecondary
            font.family: Theme.monoFont
            font.pixelSize: 9
            font.weight: Font.DemiBold
        }
    }

    HoverHandler {
        id: hover
    }
    T.ToolTip.visible: root.toolTip.length > 0 && hover.hovered
    T.ToolTip.text: root.toolTip
    T.ToolTip.delay: 550
}
