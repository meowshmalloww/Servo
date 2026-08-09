pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "."

Panel {
    id: root

    property bool expanded: false
    property int currentTab: 0
    property var tabs: ["Problems", "Output", "Terminal"]

    function showTab(index) {
        currentTab = Math.max(0, Math.min(tabs.length - 1, index));
        expanded = true;
    }

    implicitHeight: expanded ? 210 : 32

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 32
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
                        selected: root.currentTab === index && root.expanded
                        onClicked: {
                            if (root.currentTab === index && root.expanded)
                                root.expanded = false;
                            else
                                root.showTab(index);
                        }
                    }
                }

                Item {
                    Layout.fillWidth: true
                }

                Text {
                    visible: root.expanded
                    text: "No active process"
                    color: Theme.textMuted
                    font.family: Theme.monoFont
                    font.pixelSize: 8
                    Layout.rightMargin: 6
                }
            }
        }

        EmptyState {
            visible: root.expanded
            Layout.fillWidth: true
            Layout.fillHeight: true
            iconSource: root.currentTab === 0 ? Theme.icon("warning") : (root.currentTab === 1 ? Theme.icon("table") : Theme.icon("terminal"))
            title: root.currentTab === 0 ? "No problems" : (root.currentTab === 1 ? "No process output" : "No terminal session")
            description: root.currentTab === 0 ? "Diagnostics appear here when a real frontend or service error is reported." : (root.currentTab === 1 ? "Build, compiler, and connected-service output will stream here." : "A local command session has not been attached. The UI does not emulate shell output.")
        }
    }
}
