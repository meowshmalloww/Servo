import QtQuick
import QtQuick.Templates as T
import "."

T.TextField {
    id: control

    property string hint: "Search"

    implicitHeight: Theme.controlHeight
    implicitWidth: 180
    leftPadding: 30
    rightPadding: 30
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
        iconSize: Theme.iconSm
        color: control.activeFocus ? Theme.textSecondary : Theme.textMuted

        Behavior on color {
            ColorAnimation {
                duration: Theme.animFast
            }
        }
    }

    IconButton {
        visible: control.text.length > 0
        anchors.right: parent.right
        anchors.rightMargin: 2
        anchors.verticalCenter: parent.verticalCenter
        iconSource: Theme.icon("close")
        toolTip: "Clear search"
        buttonSize: 24
        onClicked: control.clear()
    }

    background: Rectangle {
        radius: Theme.cornerControl
        color: control.activeFocus || control.hovered ? Theme.fieldHover : Theme.field
        border.width: control.activeFocus ? 1 : 0
        border.color: Theme.selectionBorder

        Behavior on color {
            ColorAnimation {
                duration: Theme.animFast
                easing.type: Easing.OutCubic
            }
        }
    }
}
