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

    implicitHeight: expanded ? 212 : 34

    Behavior on implicitHeight {
        NumberAnimation {
            duration: Theme.animMove
            easing.type: Easing.InOutCubic
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 34
            color: Theme.chrome

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 4
                spacing: 2

                IconButton {
                    iconSource: Theme.icon("chevron-down")
                    toolTip: root.expanded ? "Collapse" : "Expand"
                    buttonSize: 25
                    rotation: root.expanded ? 0 : -90

                    Behavior on rotation {
                        NumberAnimation {
                            duration: Theme.animMove
                            easing.type: Easing.OutCubic
                        }
                    }

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
                    Layout.rightMargin: 8
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
