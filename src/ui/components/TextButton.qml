import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import "."

T.Button {
    id: control

    property url iconSource: ""
    property string tone: "default"
    property string toolTip: ""
    property bool compact: false
    property bool selected: false

    implicitHeight: compact ? 26 : Theme.controlHeight
    implicitWidth: Math.max(54, contentRow.implicitWidth + 22)
    leftPadding: 11
    rightPadding: 11
    hoverEnabled: true
    font.family: Theme.uiFont

    scale: control.pressed ? 0.97 : 1.0

    Behavior on scale {
        NumberAnimation {
            duration: Theme.animFast
            easing.type: Easing.OutCubic
        }
    }

    contentItem: RowLayout {
        id: contentRow
        spacing: 7

        SvgIcon {
            visible: control.iconSource.toString().length > 0
            source: control.iconSource
            iconSize: control.compact ? Theme.iconXs : Theme.iconSm
            color: {
                if (!control.enabled)
                    return Theme.textDisabled;
                if (control.tone === "primary")
                    return Theme.accentText;
                if (control.tone === "danger")
                    return Theme.error;
                return Theme.textSecondary;
            }
        }

        Text {
            text: control.text
            color: {
                if (!control.enabled)
                    return Theme.textDisabled;
                if (control.tone === "primary")
                    return Theme.accentText;
                if (control.tone === "danger")
                    return control.hovered ? Theme.error : Theme.textSecondary;
                if (control.selected)
                    return Theme.accent;
                return Theme.text;
            }
            font.family: Theme.uiFont
            font.pixelSize: 11
            font.weight: control.tone === "primary" ? Font.DemiBold : Font.Normal
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            Layout.fillWidth: true

            Behavior on color {
                ColorAnimation {
                    duration: Theme.animFast
                }
            }
        }
    }

    background: Rectangle {
        radius: Theme.cornerControl
        color: {
            if (!control.enabled && control.tone !== "primary")
                return "transparent";
            if (control.selected)
                return Theme.selection;
            if (control.down)
                return control.tone === "primary" ? Theme.accentPress : Theme.panelHover;
            if (control.hovered)
                return control.tone === "primary" ? Theme.accentHover
                                                  : (control.tone === "danger" ? Theme.tintError
                                                                               : Theme.panelHover);
            if (control.tone === "primary")
                return Theme.accent;
            if (control.tone === "danger")
                return "transparent";
            return Theme.panelRaised;
        }
        border.width: control.activeFocus ? 1 : 0
        border.color: Theme.selectionBorder

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
