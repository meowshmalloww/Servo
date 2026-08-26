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
            Layout.leftMargin: 8
            Layout.rightMargin: 8
            Layout.topMargin: 8
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
            reuseItems: true
            spacing: 1
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: Item {
                id: rowDelegate
                required property int index
                required property var display

                width: list.width
                height: Theme.rowHeight + 2

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 1
                    radius: Theme.cornerControl - 1
                    color: rowDelegate.index === root.currentIndex ? Theme.selection : (rowArea.containsMouse ? Theme.panelHover : "transparent")

                    Behavior on color {
                        ColorAnimation {
                            duration: Theme.animFast
                            easing.type: Easing.OutCubic
                        }
                    }
                }

                Rectangle {
                    visible: rowDelegate.index === root.currentIndex
                    anchors.left: parent.left
                    anchors.leftMargin: 3
                    anchors.verticalCenter: parent.verticalCenter
                    width: 3
                    height: 14
                    radius: 1.5
                    color: Theme.accent
                }

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 14
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    text: rowDelegate.display === undefined ? "" : String(rowDelegate.display)
                    color: rowDelegate.index === root.currentIndex ? Theme.text : Theme.textSecondary
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    elide: Text.ElideRight

                    Behavior on color {
                        ColorAnimation {
                            duration: Theme.animFast
                        }
                    }
                }

                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        root.currentIndex = rowDelegate.index;
                        root.activated(rowDelegate.index);
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
