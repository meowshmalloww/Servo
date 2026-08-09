import QtQuick
import QtQuick.Layouts

Column {
    id: root

    property string title: "Section"
    property string summary: ""
    property bool expanded: true
    default property alias content: body.data

    width: parent ? parent.width : implicitWidth
    height: sectionHeader.height + (expanded ? body.childrenRect.height : 0)

    Rectangle {
        id: sectionHeader
        width: root.width
        height: 34
        color: headerArea.containsMouse ? Theme.surfaceHover : Theme.panelRaised
        border.width: 1
        border.color: Theme.border

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            spacing: 8

            Text {
                text: root.expanded ? "⌄" : "›"
                color: Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 13
            }

            Text {
                text: root.title
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }

            Item { Layout.fillWidth: true }

            Text {
                visible: root.summary.length > 0
                text: root.summary
                color: Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 11
            }
        }

        MouseArea {
            id: headerArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.expanded = !root.expanded
        }
    }

    Column {
        id: body
        width: root.width
        height: root.expanded ? childrenRect.height : 0
        visible: root.expanded
    }
}
