import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T

T.TextField {
    id: control

    Layout.fillWidth: true
    Layout.fillHeight: true
    implicitHeight: Theme.controlHeight
    implicitWidth: 180
    leftPadding: 9
    rightPadding: 9
    selectByMouse: true
    selectionColor: Theme.selection
    selectedTextColor: Theme.text
    color: control.enabled ? Theme.text : Theme.textDisabled
    placeholderTextColor: Theme.textMuted
    font.family: Theme.uiFont
    font.pixelSize: 11

    background: Rectangle {
        radius: Theme.cornerControl
        color: control.enabled ? (control.hovered ? Theme.fieldHover : Theme.field) : Theme.panel
        border.width: 1
        border.color: control.activeFocus ? Theme.selectionBorder : Theme.border
    }
}
