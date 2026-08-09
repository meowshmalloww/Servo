import QtQuick

Rectangle {
    id: root

    property string text: ""
    property string tone: "neutral"

    implicitWidth: label.implicitWidth + 12
    implicitHeight: 20
    radius: Theme.cornerControl
    color: {
        if (tone === "success") return "#263529"
        if (tone === "warning") return "#3a3022"
        if (tone === "error") return "#382628"
        if (tone === "info") return Theme.selection
        return Theme.panelRaised
    }
    border.width: 1
    border.color: {
        if (tone === "success") return Theme.success
        if (tone === "warning") return Theme.warning
        if (tone === "error") return Theme.error
        if (tone === "info") return Theme.selectionBorder
        return Theme.border
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: root.text.toUpperCase()
        color: {
            if (root.tone === "success") return Theme.success
            if (root.tone === "warning") return Theme.warning
            if (root.tone === "error") return Theme.error
            if (root.tone === "info") return Theme.info
            return Theme.textMuted
        }
        font.family: Theme.uiFont
        font.pixelSize: 9
        font.weight: Font.DemiBold
    }
}
