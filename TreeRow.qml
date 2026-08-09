import QtQuick
import QtQuick.Layouts

Item {
    id: root

    property string label: "Item"
    property string glyph: "◇"
    property string suffix: ""
    property string status: ""
    property color statusColor: Theme.textMuted
    property int depth: 0
    property bool selected: false
    property bool expandable: false
    property bool expanded: false
    signal activated
    signal toggleRequested

    width: parent ? parent.width : implicitWidth
    height: Theme.rowHeight

    Rectangle {
        anchors.fill: parent
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        radius: 2
        color: root.selected
               ? Theme.tint(Theme.accent, 0.24)
               : (mouseArea.containsMouse ? Theme.surfaceHover : "transparent")

        Rectangle {
            visible: root.selected
            width: 2
            height: parent.height
            anchors.left: parent.left
            color: Theme.accent
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 10 + root.depth * 16
        anchors.rightMargin: 10
        spacing: 7

        Text {
            visible: root.expandable
            text: root.expanded ? "⌄" : "›"
            color: Theme.textMuted
            font.family: Theme.uiFont
            font.pixelSize: 13
            Layout.preferredWidth: 10
        }

        Item {
            visible: !root.expandable
            Layout.preferredWidth: 10
        }

        Text {
            text: root.glyph
            color: root.selected ? Theme.accentBright : Theme.textMuted
            font.family: Theme.uiFont
            font.pixelSize: 12
            Layout.preferredWidth: 14
        }

        Text {
            text: root.label
            color: root.enabled ? (root.selected ? Theme.text : Theme.textSecondary) : Theme.textDisabled
            font.family: Theme.uiFont
            font.pixelSize: 12
            elide: Text.ElideRight
            Layout.fillWidth: true
        }

        Text {
            visible: root.suffix.length > 0
            text: root.suffix
            color: Theme.textMuted
            font.family: Theme.monoFont
            font.pixelSize: 10
        }

        Rectangle {
            visible: root.status.length > 0
            width: 7
            height: 7
            radius: 4
            color: root.statusColor
        }
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        enabled: root.enabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            if (root.expandable) {
                root.expanded = !root.expanded
                root.toggleRequested()
            }
            root.activated()
        }
    }
}
