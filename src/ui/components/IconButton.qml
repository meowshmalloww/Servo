import QtQuick
import QtQuick.Templates as T
import "."

T.Button {
    id: control

    property url iconSource: ""
    property string toolTip: ""
    property int buttonSize: 28
    property bool selected: false

    implicitWidth: buttonSize
    implicitHeight: buttonSize
    hoverEnabled: true

    contentItem: SvgIcon {
        anchors.centerIn: parent
        source: control.iconSource
        iconSize: 15
        opacity: control.enabled ? 1 : 0.4
    }

    background: Rectangle {
        radius: Theme.cornerControl
        color: control.selected ? Theme.selection
                                : (control.down ? Theme.panelHover
                                                : (control.hovered ? Theme.panelRaised : "transparent"))
        border.width: control.selected || control.activeFocus ? 1 : 0
        border.color: control.activeFocus ? Theme.selectionBorder : Theme.borderStrong
    }

    T.ToolTip.visible: control.toolTip.length > 0 && control.hovered
    T.ToolTip.text: control.toolTip
    T.ToolTip.delay: 550
}
