pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "."

Panel {
    id: root

    property bool expanded: false
    property int currentTab: 0
    property var tabs: ["Problems", "Output", "Files"]

    implicitHeight: expanded ? 150 : 34

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
                anchors.leftMargin: 4
                spacing: 0

                IconButton {
                    iconSource: root.expanded ? Theme.icon("chevron-down") : Theme.icon("chevron-right")
                    toolTip: root.expanded ? "Collapse" : "Expand"
                    buttonSize: 27
                    onClicked: root.expanded = !root.expanded
                }

                Repeater {
                    model: root.tabs

                    delegate: TextButton {
                        required property int index
                        required property string modelData
                        text: modelData
                        compact: true
                        onClicked: {
                            root.currentTab = index
                            root.expanded = true
                        }
                    }
                }

                Item { Layout.fillWidth: true }
            }
        }

        EmptyState {
            visible: root.expanded
            Layout.fillWidth: true
            Layout.fillHeight: true
            iconSource: root.currentTab === 0 ? Theme.icon("warning")
                                                : (root.currentTab === 1 ? Theme.icon("table") : Theme.icon("folder"))
            title: root.currentTab === 0 ? "No problems"
                                          : (root.currentTab === 1 ? "No process output" : "No generated files")
            description: "This panel is connected to workspace services and stays empty until they publish records."
        }
    }
}
