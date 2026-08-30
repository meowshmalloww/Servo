import QtQuick
import QtQuick.Layouts
import "."

Rectangle {
    id: root

    property string text: ""
    property string tone: "neutral"

    readonly property color toneColor: {
        if (root.tone === "success")
            return Theme.success;
        if (root.tone === "warning")
            return Theme.warning;
        if (root.tone === "error")
            return Theme.error;
        if (root.tone === "info")
            return Theme.info;
        return Theme.textMuted;
    }

    implicitWidth: Math.min(140, Math.max(56, row.implicitWidth + 14))
    implicitHeight: 20
    radius: 6
    clip: true
    Layout.maximumWidth: 140
    color: {
        if (root.tone === "success")
            return Theme.tintSuccess;
        if (root.tone === "warning")
            return Theme.tintWarning;
        if (root.tone === "error")
            return Theme.tintError;
        if (root.tone === "info")
            return Theme.tintInfo;
        return Theme.panelRaised;
    }
    border.width: root.tone === "neutral" ? 1 : 0
    border.color: Theme.borderSoft

    Behavior on color {
        enabled: Theme.motionEnabled
        ColorAnimation {
            duration: Theme.animBase
            easing.type: Easing.OutCubic
        }
    }

    RowLayout {
        id: row
        anchors.centerIn: parent
        spacing: 5

        SvgIcon {
            visible: root.tone !== "neutral"
            source: {
                if (root.tone === "success")
                    return Theme.icon("check");
                if (root.tone === "warning")
                    return Theme.icon("warning");
                if (root.tone === "error")
                    return Theme.icon("error");
                return Theme.icon("info");
            }
            iconSize: Theme.iconXs
            color: root.toneColor
        }

        Text {
            text: root.text.toUpperCase()
            color: root.toneColor
            font.family: Theme.uiFont
            font.pixelSize: 9
            font.weight: Font.DemiBold
            font.letterSpacing: 0.4
            elide: Text.ElideRight
            maximumLineCount: 1
        }
    }
}
