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

    implicitWidth: row.implicitWidth + 14
    implicitHeight: 20
    radius: height / 2 - 3
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

    Behavior on color {
        ColorAnimation {
            duration: Theme.animBase
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
        }
    }
}
