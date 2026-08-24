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

    Item {
        id: header
        width: root.width
        height: 34

        Rectangle {
            anchors.fill: parent
            radius: Theme.cornerControl
            color: headerArea.containsMouse ? Theme.panelHover : "transparent"
            opacity: headerArea.containsMouse ? 0.6 : 1

            Behavior on opacity {
                NumberAnimation {
                    duration: Theme.animFast
                }
            }
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 7

            SvgIcon {
                source: Theme.icon("chevron-down")
                iconSize: Theme.iconSm
                color: Theme.textMuted
                rotation: root.expanded ? 0 : -90

                Behavior on rotation {
                    NumberAnimation {
                        duration: Theme.animMove
                        easing.type: Easing.OutCubic
                    }
                }
            }

            Text {
                text: root.title
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: 10
                font.weight: Font.DemiBold
                font.letterSpacing: 0.7
                font.capitalization: Font.AllUppercase
            }

            Item {
                Layout.fillWidth: true
            }

            Text {
                visible: root.summary.length > 0
                text: root.summary
                color: Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 10
                elide: Text.ElideRight
                Layout.maximumWidth: 240
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
        visible: height > 0
        opacity: root.expanded ? 1 : 0
        spacing: 0

        clip: true

        Behavior on height {
            NumberAnimation {
                duration: Theme.animMove
                easing.type: Easing.InOutCubic
            }
        }

        Behavior on opacity {
            NumberAnimation {
                duration: Theme.animFast
                easing.type: Easing.OutCubic
            }
        }
    }
}
