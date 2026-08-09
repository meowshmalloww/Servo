import QtQuick
import QtQuick.Layouts
import "."

Column {
    id: root

    property string title: ""
    property string summary: ""
    property bool expanded: true
    default property alias content: body.data

    width: parent ? parent.width : implicitWidth
    height: header.height + body.height
    spacing: 0

    Rectangle {
        id: header
        width: root.width
        height: 32
        color: headerArea.containsMouse ? Theme.panelHover : Theme.panelRaised
        border.width: 1
        border.color: Theme.borderSoft

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 10
            spacing: 7

            SvgIcon {
                source: root.expanded ? Theme.icon("chevron-down") : Theme.icon("chevron-right")
                iconSize: 13
            }

            Text {
                text: root.title
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 11
                font.weight: Font.DemiBold
            }

            Item { Layout.fillWidth: true }

            Text {
                visible: root.summary.length > 0
                text: root.summary
                color: Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 10
                elide: Text.ElideRight
                Layout.maximumWidth: 220
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

    ColumnLayout {
        id: body
        width: root.width
        height: root.expanded ? implicitHeight : 0
        visible: root.expanded
        spacing: 0
    }
}
