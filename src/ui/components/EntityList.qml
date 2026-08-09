pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "."

Item {
    id: root

    property var model: null
    property string emptyTitle: "Nothing here"
    property string emptyDescription: ""
    property url emptyIcon: Theme.icon("file")
    property string searchPlaceholder: "Search"
    property bool searchable: true
    property int currentIndex: -1
    signal activated(int index)

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            visible: root.searchable
            Layout.fillWidth: true
            Layout.leftMargin: 7
            Layout.rightMargin: 7
            Layout.topMargin: 7
            Layout.bottomMargin: 6
            spacing: 5

            SearchField {
                Layout.fillWidth: true
                hint: root.searchPlaceholder
            }

            IconButton {
                iconSource: Theme.icon("filter")
                toolTip: "Filter"
                buttonSize: Theme.controlHeight
                enabled: root.model !== null
            }
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: root.model
            currentIndex: root.currentIndex
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
                id: rowDelegate
                required property int index
                required property var display

                width: list.width
                height: Theme.rowHeight
                color: rowDelegate.index === root.currentIndex
                       ? Theme.selection
                       : (rowArea.containsMouse ? Theme.panelHover : "transparent")
                border.width: rowDelegate.index === root.currentIndex ? 1 : 0
                border.color: Theme.selectionBorder

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 10
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    text: rowDelegate.display === undefined ? "" : String(rowDelegate.display)
                    color: Theme.textSecondary
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }

                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        root.currentIndex = rowDelegate.index
                        root.activated(rowDelegate.index)
                    }
                }
            }
        }
    }

    EmptyState {
        anchors.fill: parent
        anchors.topMargin: root.searchable ? 44 : 0
        visible: list.count === 0
        iconSource: root.emptyIcon
        title: root.emptyTitle
        description: root.emptyDescription
    }
}
