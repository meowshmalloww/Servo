pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "."

Panel {
    id: root

    property string title: "Metric"
    property string unit: ""
    property var values: []
    property real minimum: 0
    property real maximum: 1
    property color lineColor: Theme.accent

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PanelHeader {
            title: root.title
            subtitle: root.unit
            iconSource: Theme.icon("chart")
            Layout.fillWidth: true
        }

        Item {
            id: plotArea
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 10
            clip: true

            Column {
                anchors.fill: parent
                spacing: Math.max(1, (height - 4) / 4)
                visible: root.values !== null && root.values.length >= 2
                Repeater {
                    model: 5
                    Rectangle { width: plotArea.width; height: 1; color: Theme.borderSoft }
                }
            }

            LinePlotItem {
                anchors.fill: parent
                values: root.values
                minimum: root.minimum
                maximum: root.maximum
                lineColor: root.lineColor
                visible: root.values !== null && root.values.length >= 2
            }

            EmptyState {
                anchors.fill: parent
                visible: root.values === null || root.values.length < 2
                iconSource: Theme.icon("chart")
                title: "No series data"
                description: "Metric samples will appear when a connected job publishes them."
            }
        }
    }
}
