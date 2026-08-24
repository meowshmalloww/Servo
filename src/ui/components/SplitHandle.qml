import QtQuick
import QtQuick.Templates as T
import "."

Item {
    id: root

    readonly property bool verticalDivider: width < height

    implicitWidth: 8
    implicitHeight: 8

    Rectangle {
        anchors.centerIn: parent
        width: root.verticalDivider ? 2 : 22
        height: root.verticalDivider ? 22 : 2
        radius: 1
        color: hover.hovered ? Theme.accent : "transparent"

        Behavior on color {
            ColorAnimation {
                duration: Theme.animFast
            }
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
