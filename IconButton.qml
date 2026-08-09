import QtQuick
import QtQuick.Controls.Basic

ToolButton {
    id: control

    property string glyph: "·"
    property string toolTip: ""
    property bool selected: false
    property int buttonSize: 28

    implicitWidth: buttonSize
    implicitHeight: buttonSize
    hoverEnabled: true

    contentItem: Text {
        text: control.glyph
        color: control.enabled
               ? (control.selected ? Theme.text : Theme.textSecondary)
               : Theme.textDisabled
        font.family: Theme.uiFont
        font.pixelSize: 14
        font.weight: control.selected ? Font.DemiBold : Font.Normal
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }

    background: Rectangle {
        radius: 2
        color: control.down
               ? Theme.surfacePressed
               : (control.selected ? Theme.surfaceHover
                                   : (control.hovered ? Theme.surface : "transparent"))
        border.width: control.selected || control.activeFocus ? 1 : 0
        border.color: control.activeFocus ? Theme.accent : Theme.borderStrong
    }

    ToolTip.visible: hovered && toolTip.length > 0
    ToolTip.text: toolTip
    ToolTip.delay: 500
}
