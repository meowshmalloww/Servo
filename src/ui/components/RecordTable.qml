pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "."

// Lightweight table over an explicit array of plain JS objects.
// Used where records come from parsed backend payloads rather than a
// QAbstractItemModel. Every displayed string comes from the provided rows.
Item {
    id: root

    property var rows: []
    property var columns: []
    property string emptyTitle: "No records"
    property string emptyDescription: ""
    property url emptyIcon: Theme.icon("table")
    property int rowHeight: 32
    property int currentRow: -1
    signal rowActivated(int row)

    Column {
        id: headerRow
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right

        Repeater {
            model: root.columns

            delegate: Rectangle {
                id: headerCell
                required property int index
                required property var modelData
                x: {
                    let offset = 0
                    for (let i = 0; i < index; ++i)
                        offset += root.columns[i].width === undefined ? 120 : root.columns[i].width
                    return offset
                }
                width: modelData.width === undefined ? 120 : modelData.width
                height: 30
                color: "transparent"

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

    Rectangle {
        anchors.top: headerRow.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        height: 1
        color: Theme.borderSoft
        opacity: 0.5
    }

    ListView {
        id: list
        anchors.top: headerRow.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: root.rows.length
        currentIndex: root.currentRow
        reuseItems: true
        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
        }

        delegate: Item {
            id: rowDelegate
            required property int index
            width: list.width
            height: root.rowHeight

            Row {
                anchors.fill: parent

                Repeater {
                    model: root.columns

                    delegate: Rectangle {
                        id: cell
                        required property var modelData
                        required property int index
                        readonly property var rowValues: root.rows[rowDelegate.index] ?? {}
                        width: modelData.width === undefined ? 120 : modelData.width
                        height: parent.height
                        color: rowDelegate.index === root.currentRow
                               ? Theme.selection
                               : (cellMouse.containsMouse ? Theme.panelHover : "transparent")

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
                            text: {
                                const field = cell.modelData.field
                                if (field === undefined)
                                    return ""
                                const value = cell.rowValues[field]
                                return value === undefined || value === null ? "-" : String(value)
                            }
                            color: rowDelegate.index === root.currentRow ? Theme.text : Theme.textSecondary
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
                                root.currentRow = rowDelegate.index
                                root.rowActivated(rowDelegate.index)
                            }
                        }
                    }
                }
            }
        }
    }

    EmptyState {
        anchors.fill: parent
        anchors.topMargin: 30
        visible: root.rows.length === 0
        iconSource: root.emptyIcon
        title: root.emptyTitle
        description: root.emptyDescription
    }
}
