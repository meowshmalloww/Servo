pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "."

Panel {
    id: root

    property string title: "Viewport"
    property string emptyTitle: "No world loaded"
    property string emptyDescription: "Open or compile a world to activate the viewport."
    property bool available: false

    color: "#17191b"

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 34
            color: Theme.chrome
            border.width: 1
            border.color: Theme.borderSoft

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 6
                spacing: 6

                SvgIcon { source: Theme.icon("camera"); iconSize: 14 }
                Text { text: root.title; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10 }
                Item { Layout.fillWidth: true }
                IconButton { iconSource: Theme.icon("cube"); toolTip: "Viewport mode"; enabled: root.available; buttonSize: 25 }
                IconButton { iconSource: Theme.icon("settings"); toolTip: "Viewport settings"; enabled: root.available; buttonSize: 25 }
            }
        }

        Item {
            id: surface
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            Repeater {
                model: 12
                Rectangle {
                    required property int index
                    x: index * surface.width / 11
                    width: 1
                    height: surface.height
                    color: Theme.borderSoft
                    opacity: 0.28
                }
            }

            Repeater {
                model: 8
                Rectangle {
                    required property int index
                    y: index * surface.height / 7
                    width: surface.width
                    height: 1
                    color: Theme.borderSoft
                    opacity: 0.28
                }
            }

            EmptyState {
                anchors.fill: parent
                visible: !root.available
                iconSource: Theme.icon("cube")
                title: root.emptyTitle
                description: root.emptyDescription
            }
        }
    }
}
