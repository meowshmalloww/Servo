import QtQuick
import QtQuick.Templates as T
import "."

Item {
    id: root

    readonly property bool verticalDivider: width < height

    implicitWidth: 7
    implicitHeight: 7

    Rectangle {
        anchors.fill: parent
        color: Theme.borderSoft
        opacity: hover.hovered || dragHandler.active ? 0 : 0.55
        visible: root.verticalDivider
    }
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        height: 1
        color: Theme.borderSoft
        opacity: hover.hovered || dragHandler.active ? 0 : 0.55
        visible: !root.verticalDivider
    }

    Rectangle {
        anchors.centerIn: parent
        width: root.verticalDivider ? 2 : 28
        height: root.verticalDivider ? 28 : 2
        radius: 1
        color: Theme.accent
        opacity: hover.hovered || dragHandler.active ? 1 : 0

        Behavior on opacity {
            enabled: Theme.motionEnabled
            NumberAnimation { duration: Theme.animFast; easing.type: Easing.OutCubic }
        }
    }

    HoverHandler {
        id: hover
        cursorShape: root.verticalDivider ? Qt.SplitHCursor : Qt.SplitVCursor
    }
    DragHandler { id: dragHandler; target: null }

    T.ToolTip.visible: hover.hovered
    T.ToolTip.text: "Drag to resize"
    T.ToolTip.delay: 650
}
