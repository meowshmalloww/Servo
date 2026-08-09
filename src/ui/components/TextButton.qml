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
    implicitWidth: Math.max(54, contentRow.implicitWidth + 18)
    leftPadding: 9
    rightPadding: 9
    hoverEnabled: true

    contentItem: RowLayout {
        id: contentRow
        spacing: 7

        SvgIcon {
            visible: control.iconSource.toString().length > 0
            source: control.iconSource
            iconSize: control.compact ? 13 : 14
            opacity: control.enabled ? 1 : 0.45
        }

        Text {
            text: control.text
            color: control.enabled ? Theme.text : Theme.textDisabled
            font.family: Theme.uiFont
            font.pixelSize: 11
            font.weight: control.tone === "primary" ? Font.DemiBold : Font.Normal
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            Layout.fillWidth: true
        }
    }

    background: Rectangle {
        radius: Theme.cornerControl
        color: {
            if (!control.enabled)
                return Theme.field;
            if (control.selected)
                return Theme.selection;
            if (control.down)
                return control.tone === "primary" ? Theme.selectionBorder : Theme.panelHover;
            if (control.hovered)
                return control.tone === "primary" ? Theme.accentHover : Theme.panelHover;
            if (control.tone === "primary")
                return Theme.accent;
            if (control.tone === "danger")
                return "#3b292b";
            return Theme.panelRaised;
        }
        border.width: 1
        border.color: {
            if (!control.enabled)
                return Theme.border;
            if (control.activeFocus)
                return Theme.selectionBorder;
            if (control.selected)
                return Theme.selectionBorder;
            if (control.tone === "primary")
                return Theme.accentHover;
            if (control.tone === "danger")
                return Theme.error;
            return control.hovered ? Theme.borderStrong : Theme.border;
        }
    }

    T.ToolTip.visible: control.toolTip.length > 0 && control.hovered
    T.ToolTip.text: control.toolTip
    T.ToolTip.delay: 550
}
