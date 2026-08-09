import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

Button {
    id: control

    property string glyph: ""
    property string tone: "default"
    property bool compact: false
    property string toolTip: ""

    implicitHeight: compact ? 26 : Theme.controlHeight
    implicitWidth: Math.max(compact ? 54 : 72, contentRow.implicitWidth + leftPadding + rightPadding)
    leftPadding: compact ? 9 : 12
    rightPadding: compact ? 9 : 12
    spacing: 7
    hoverEnabled: true

    font.family: Theme.uiFont
    font.pixelSize: 12
    font.weight: tone === "primary" ? Font.DemiBold : Font.Normal

    contentItem: RowLayout {
        id: contentRow
        spacing: control.spacing

        Text {
            visible: control.glyph.length > 0
            text: control.glyph
            color: control.enabled ? control.buttonTextColor() : Theme.textDisabled
            font.family: Theme.uiFont
            font.pixelSize: 12
            Layout.alignment: Qt.AlignVCenter
        }

        Text {
            text: control.text
            color: control.enabled ? control.buttonTextColor() : Theme.textDisabled
            font: control.font
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            Layout.alignment: Qt.AlignVCenter
        }
    }

    background: Rectangle {
        radius: 2
        color: {
            if (!control.enabled)
                return Theme.surface
            if (control.down)
                return control.tone === "primary" ? Theme.accentDim : Theme.surfacePressed
            if (control.hovered)
                return control.tone === "primary" ? Theme.accentBright : Theme.surfaceHover
            if (control.tone === "primary")
                return Theme.accent
            if (control.tone === "danger")
                return Theme.tint(Theme.red, 0.14)
            return Theme.surface
        }
        border.width: 1
        border.color: {
            if (control.activeFocus)
                return Theme.accentBright
            if (control.tone === "primary")
                return control.hovered ? Theme.accentBright : Theme.accent
            if (control.tone === "danger")
                return Theme.tint(Theme.red, 0.7)
            return control.hovered ? Theme.borderStrong : Theme.border
        }
    }

    ToolTip.visible: hovered && toolTip.length > 0
    ToolTip.text: toolTip
    ToolTip.delay: 500

    function buttonTextColor() {
        if (control.tone === "primary")
            return "#101214"
        if (control.tone === "danger")
            return Theme.red
        return Theme.text
    }
}
