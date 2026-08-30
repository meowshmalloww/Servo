import QtQuick
import QtQuick.Templates as T
import "."

T.Button {
    id: control

    property url iconSource: ""
    property string toolTip: ""
    property int buttonSize: 26
    property bool selected: false
    property string tone: "default"

    text: toolTip
    implicitWidth: buttonSize
    implicitHeight: buttonSize
    hoverEnabled: true
    font.family: Theme.uiFont
    Accessible.role: Accessible.Button
    Accessible.name: toolTip

    contentItem: SvgIcon {
        anchors.centerIn: parent
        source: control.iconSource
        iconSize: Math.round(control.buttonSize * 0.54)
        color: {
            if (!control.enabled)
                return Theme.textDisabled;
            if (control.selected || (control.tone === "primary" && control.checked))
                return Theme.accent;
            if (control.tone === "danger")
                return Theme.error;
            return Theme.textSecondary;
        }

        Behavior on scale {
            NumberAnimation {
                duration: Theme.animFast
                easing.type: Easing.OutCubic
            }
        }
    }

    scale: control.pressed && control.enabled ? 0.94 : 1.0

    Behavior on scale {
        enabled: Theme.motionEnabled
        NumberAnimation {
            duration: 90
            easing.type: Easing.OutCubic
        }
    }

    background: Rectangle {
        radius: Theme.cornerControl
        color: {
            if (control.tone === "danger" && !control.selected)
                return control.hovered ? Theme.tintError : "transparent";
            if (control.selected)
                return Theme.selection;
            if (control.down)
                return Theme.panelHover;
            if (control.hovered)
                return Theme.panelRaised;
            return "transparent";
        }

        Behavior on color {
            ColorAnimation {
                duration: Theme.animFast
                easing.type: Easing.OutCubic
            }
        }
    }

    T.ToolTip.visible: control.toolTip.length > 0 && control.hovered
    T.ToolTip.text: control.toolTip
    T.ToolTip.delay: 550
}
