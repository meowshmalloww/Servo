import QtQuick
import QtQuick.Templates as T
import "."

Item {
    id: root

    readonly property bool verticalDivider: width < height

    implicitWidth: 9
    implicitHeight: 9

    Rectangle {
        anchors.centerIn: parent
        width: root.verticalDivider ? 1 : parent.width
        height: root.verticalDivider ? parent.height : 1
        color: hover.hovered ? Theme.selectionBorder : Theme.borderSoft
    }

    Rectangle {
        anchors.centerIn: parent
        width: root.verticalDivider ? 9 : 28
        height: root.verticalDivider ? 28 : 9
        radius: 2
        color: hover.hovered ? Theme.panelRaised : Theme.chrome
        border.width: 1
        border.color: hover.hovered ? Theme.selectionBorder : Theme.border

        SvgIcon {
            anchors.centerIn: parent
            source: Theme.icon(root.verticalDivider ? "resize-horizontal" : "resize-vertical")
            iconSize: 12
            opacity: hover.hovered ? 1 : 0.55
        }
    }

    HoverHandler {
        id: hover
        cursorShape: root.verticalDivider ? Qt.SplitHCursor : Qt.SplitVCursor
    }

    T.ToolTip.visible: hover.hovered
    T.ToolTip.text: "Drag to resize"
    T.ToolTip.delay: 650
}
