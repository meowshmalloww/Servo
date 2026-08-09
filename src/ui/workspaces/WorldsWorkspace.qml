pragma ComponentBehavior: Bound

import QtCore
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../components"

Item {
    id: root

    function resetLayout() {
        Session.viewportFocusMode = false;
        worldLibrary.SplitView.preferredWidth = 248;
        worldInspector.SplitView.preferredWidth = 300;
    }

    Settings {
        id: layoutSettings
        category: "WorldEditorLayout"
        property var horizontalSplitState
    }

    Component.onCompleted: {
        if (layoutSettings.horizontalSplitState !== undefined)
            worldSplit.restoreState(layoutSettings.horizontalSplitState);
    }

    Component.onDestruction: {
        if (!Session.viewportFocusMode)
            layoutSettings.horizontalSplitState = worldSplit.saveState();
    }

    Connections {
        target: Session
        function onResetWorkspaceLayoutRequested() {
            root.resetLayout();
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "World Editor"
            subtitle: Session.projectOpen ? Session.projectName : "No project open"
            iconSource: Theme.icon("world")
            Layout.fillWidth: true

            TextButton {
                text: Session.recordingSelected ? Session.recordingName : "Select recording"
                iconSource: Theme.icon("camera")
                enabled: Session.projectOpen
                toolTip: Session.projectOpen ? "Select an authorized sensor recording" : "Open a project first"
                onClicked: Session.importRecordingRequested()
            }
        }

        SplitView {
            id: worldSplit
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: SplitHandle {}

            Panel {
                id: worldLibrary
                visible: !Session.viewportFocusMode
                SplitView.preferredWidth: 248
                SplitView.minimumWidth: 180
                SplitView.maximumWidth: 520

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Worlds"
                        subtitle: Session.worldModel === null ? "No source" : "Connected"
                        iconSource: Theme.icon("folder")
                        Layout.fillWidth: true
                    }

                    EntityList {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: Session.worldModel
                        searchPlaceholder: "Filter worlds"
                        emptyIcon: Theme.icon("world")
                        emptyTitle: "No compiled worlds"
                        emptyDescription: "World records appear here only after a compiler service publishes them."
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 46
                        color: Theme.chrome
                        border.width: 1
                        border.color: Theme.borderSoft

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 9
                            anchors.rightMargin: 9
                            spacing: 8

                            SvgIcon {
                                source: Theme.icon("sensor")
                                iconSize: 14
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0
                                Text {
                                    text: "SOURCE"
                                    color: Theme.textMuted
                                    font.family: Theme.uiFont
                                    font.pixelSize: 8
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    text: Session.recordingSelected ? Session.recordingName : "No recording selected"
                                    color: Session.recordingSelected ? Theme.textSecondary : Theme.textDisabled
                                    font.family: Theme.uiFont
                                    font.pixelSize: 9
                                    elide: Text.ElideMiddle
                                    Layout.fillWidth: true
                                }
                            }
                        }
                    }
                }
            }

            ViewportSurface {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 440
                title: "World / Perspective"
                available: false
                emptyTitle: "3D world viewport ready"
                emptyDescription: "Attach a compiled appearance layer, metric geometry, and scene graph when those services are available."
            }

            Panel {
                id: worldInspector
                visible: !Session.viewportFocusMode
                SplitView.preferredWidth: 300
                SplitView.minimumWidth: 230
                SplitView.maximumWidth: 560

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Inspector"
                        subtitle: "No selection"
                        iconSource: Theme.icon("inspector")
                        Layout.fillWidth: true
                    }

                    ScrollView {
                        id: inspectorScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        Column {
                            width: inspectorScroll.availableWidth

                            Section {
                                title: "World"
                                PropertyRow {
                                    label: "Source"
                                    labelWidth: 82
                                    TextInput {
                                        text: Session.recordingName
                                        placeholderText: "Not attached"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Appearance"
                                    labelWidth: 82
                                    TextInput {
                                        placeholderText: "Not compiled"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Geometry"
                                    labelWidth: 82
                                    TextInput {
                                        placeholderText: "Not compiled"
                                        readOnly: true
                                    }
                                }
                            }

                            Section {
                                title: "Scene"
                                PropertyRow {
                                    label: "Actors"
                                    labelWidth: 82
                                    TextInput {
                                        placeholderText: "No scene model"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Sensors"
                                    labelWidth: 82
                                    TextInput {
                                        placeholderText: "No sensor rig"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Road graph"
                                    labelWidth: 82
                                    TextInput {
                                        placeholderText: "Not available"
                                        readOnly: true
                                    }
                                }
                            }

                            Section {
                                title: "Trust"
                                PropertyRow {
                                    label: "Metric scale"
                                    labelWidth: 82
                                    TextInput {
                                        placeholderText: "Unverified"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Collision"
                                    labelWidth: 82
                                    TextInput {
                                        placeholderText: "Not attached"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Uncertainty"
                                    labelWidth: 82
                                    TextInput {
                                        placeholderText: "No map"
                                        readOnly: true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
