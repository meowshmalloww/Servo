import QtQuick
import QtQuick.Controls.Basic

TextField {
    id: control

    anchors.fill: parent
    implicitHeight: Theme.controlHeight
    leftPadding: 9
    rightPadding: 9
    color: Theme.text
    placeholderTextColor: Theme.textMuted
    selectionColor: Theme.accentDim
    selectedTextColor: Theme.text
    font.family: Theme.uiFont
    font.pixelSize: 12

    background: Rectangle {
        radius: 2
        color: Theme.field
        border.width: 1
        border.color: control.activeFocus ? Theme.accent : (control.hovered ? Theme.borderStrong : Theme.border)
    }
}
