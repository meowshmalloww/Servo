pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "."

Panel {
    id: root

    property bool expanded: false
    property int currentTab: 0
    property var tabs: ["Problems", "Output", "Terminal"]
    readonly property var tabIcons: ["warning", "table", "terminal"]

    function showTab(index) {
        currentTab = Math.max(0, Math.min(tabs.length - 1, index));
        expanded = true;
    }

    implicitHeight: expanded ? 248 : 32

    Behavior on implicitHeight {
        enabled: Theme.motionEnabled
        NumberAnimation {
            duration: Theme.animDrawer
            easing.type: Easing.OutCubic
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 31
            color: Theme.chrome

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 4
                spacing: 2

                IconButton {
                    iconSource: Theme.icon("chevron-down")
                    toolTip: root.expanded ? "Collapse" : "Expand"
                    buttonSize: 23
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
                        iconSource: Theme.icon(root.tabIcons[index])
                        compact: true
                        selected: root.currentTab === index && root.expanded
                        implicitHeight: 27
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
                    text: root.expanded ? "SUPPORTING OUTPUT" : ""
                    color: Theme.textMuted
                    font.family: Theme.uiFont
                    font.pixelSize: 8
                    font.letterSpacing: 0.6
                    Layout.rightMargin: 8
                }
            }
        }

        EmptyState {
            visible: root.expanded
            Layout.fillWidth: true
            Layout.fillHeight: true
            iconSource: root.currentTab === 0 ? Theme.icon("warning") : (root.currentTab === 1 ? Theme.icon("table") : Theme.icon("terminal"))
            title: root.currentTab === 0 ? "No problems" : (root.currentTab === 1 ? "No output yet" : "No terminal attached")
            description: root.currentTab === 0 ? "Errors and warnings appear here." : (root.currentTab === 1 ? "Build and run output appears here." : "Connect a local command session when needed.")
        }
    }
}
