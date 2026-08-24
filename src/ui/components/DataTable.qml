pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "."

Item {
    id: root

    property var model: null
    property var columns: []
    property string emptyTitle: "No records"
    property string emptyDescription: ""
    property url emptyIcon: Theme.icon("table")
    property int rowHeight: 32
    property int currentRow: -1
    signal rowActivated(int row)

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            id: headerRow
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            color: "transparent"

            Row {
                anchors.fill: parent

                Repeater {
                    model: root.columns

                    delegate: Item {
                        id: headerCell
                        required property var modelData
                        width: modelData.width === undefined ? 120 : modelData.width
                        height: parent.height

                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 10
                            anchors.right: parent.right
                            anchors.rightMargin: 6
                            anchors.verticalCenter: parent.verticalCenter
                            text: headerCell.modelData.title === undefined ? "" : headerCell.modelData.title
                            color: Theme.textMuted
                            font.family: Theme.uiFont
                            font.pixelSize: 9
                            font.weight: Font.DemiBold
                            font.letterSpacing: 0.7
                            font.capitalization: Font.AllUppercase
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            Layout.leftMargin: 10
            Layout.rightMargin: 10
            color: Theme.borderSoft
            opacity: 0.5
        }

        TableView {
            id: table
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: root.model
            boundsBehavior: Flickable.StopAtBounds
            columnSpacing: 0
            rowSpacing: 0
            reuseItems: true
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }
            ScrollBar.horizontal: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            columnWidthProvider: function (column) {
                if (column < 0 || column >= root.columns.length)
                    return 120;
                const value = root.columns[column].width;
                return value === undefined ? 120 : value;
            }

            rowHeightProvider: function () {
                return root.rowHeight;
            }

            delegate: Rectangle {
                id: cell
                required property int row
                required property int column
                required property var display

                color: cell.row === root.currentRow ? Theme.selection : (cellMouse.containsMouse ? Theme.panelHover : "transparent")

                Behavior on color {
                    ColorAnimation {
                        duration: Theme.animFast
                        easing.type: Easing.OutCubic
                    }
                }

                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 6
                    text: cell.display === undefined || cell.display === null ? "" : String(cell.display)
                    color: cell.row === root.currentRow ? Theme.text : Theme.textSecondary
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }

                MouseArea {
                    id: cellMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        root.currentRow = cell.row;
                        root.rowActivated(cell.row);
                    }
                }
            }
        }
    }

    EmptyState {
        anchors.fill: parent
        anchors.topMargin: 30
        visible: table.rows === 0
        iconSource: root.emptyIcon
        title: root.emptyTitle
        description: root.emptyDescription
    }
}
