import QtQuick
import QtQuick.Templates as T
import "."

T.TextField {
    id: control

    property string hint: "Search"

    implicitHeight: Theme.controlHeight
    implicitWidth: 180
    leftPadding: 32
    rightPadding: 32
    selectByMouse: true
    placeholderText: hint
    color: Theme.text
    placeholderTextColor: Theme.textMuted
    selectionColor: Theme.selection
    selectedTextColor: Theme.text
    font.family: Theme.uiFont
    font.pixelSize: 11

    SvgIcon {
        anchors.left: parent.left
        anchors.leftMargin: 9
        anchors.verticalCenter: parent.verticalCenter
        source: Theme.icon("search")
        iconSize: 14
        opacity: 0.75
    }

    IconButton {
        visible: control.text.length > 0
        anchors.right: parent.right
        anchors.rightMargin: 2
        anchors.verticalCenter: parent.verticalCenter
        iconSource: Theme.icon("close")
        toolTip: "Clear search"
        buttonSize: 26
        onClicked: control.clear()
    }

    background: Rectangle {
        radius: Theme.cornerControl
        color: control.hovered ? Theme.fieldHover : Theme.field
        border.width: 1
        border.color: control.activeFocus ? Theme.selectionBorder : Theme.border
    }
}
