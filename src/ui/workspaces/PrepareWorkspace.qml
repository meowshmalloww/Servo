pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import "../components"

Item {
    id: root

    property url policyUrl: ""
    property url vehicleConfigUrl: ""
    property url calibrationUrl: ""
    property string selectedAsset: ""

    readonly property bool compilerAvailable: false
    readonly property bool requiredInputsPresent: Session.projectOpen
                                                  && policyUrl.toString().length > 0
                                                  && vehicleConfigUrl.toString().length > 0
                                                  && calibrationUrl.toString().length > 0
                                                  && Session.recordingSelected

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "Prepare"
            subtitle: "Policy adapter, physical system, sensor rig, recordings, and world compiler"
            iconSource: Theme.icon("project")
            Layout.fillWidth: true

            TextButton {
                text: "Open Project"
                iconSource: Theme.icon("open")
                onClicked: Session.openProjectRequested()
            }

            TextButton {
                text: "Select Recording"
                iconSource: Theme.icon("camera")
                enabled: Session.projectOpen
                onClicked: Session.importRecordingRequested()
            }

            TextButton {
                text: "Build World"
                iconSource: Theme.icon("build")
                tone: "primary"
                enabled: root.requiredInputsPresent && root.compilerAvailable
                toolTip: root.compilerAvailable ? "Build executable world" : "World compiler service is not connected"
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: SplitHandle { }

            Panel {
                SplitView.preferredWidth: 270
                SplitView.minimumWidth: 220
                SplitView.maximumWidth: 380

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Project Files"
                        subtitle: Session.projectOpen ? Session.projectName : "No project"
                        iconSource: Theme.icon("folder")
                        Layout.fillWidth: true
                    }

                    EntityList {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: Session.projectTreeModel
                        searchPlaceholder: "Filter project files"
                        emptyIcon: Session.projectOpen ? Theme.icon("folder") : Theme.icon("project")
                        emptyTitle: Session.projectOpen ? "Project index unavailable" : "No project open"
                        emptyDescription: Session.projectOpen
                                          ? "The project adapter has not published its file model."
                                          : "Open a .servo project to load its policies, platform, sensors, recordings, and test plans."
                    }
                }
            }

            SplitView {
                orientation: Qt.Vertical
                SplitView.fillWidth: true
                SplitView.minimumWidth: 620
                handle: SplitHandle { }

                Panel {
                    SplitView.fillHeight: true
                    SplitView.minimumHeight: 420

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Study Configuration"
                            subtitle: Session.projectOpen ? Session.fileName(Session.projectUrl) : "Read only until a project is open"
                            iconSource: Theme.icon("settings")
                            Layout.fillWidth: true
                        }

                        ScrollView {
                            id: formScroll
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            contentWidth: availableWidth
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                            Column {
                                width: formScroll.availableWidth
                                spacing: 0

                                Section {
                                    title: "Policy Adapter"
                                    summary: "Inference and optional training interface"

                                    PropertyRow {
                                        label: "Policy package"
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Layout.fillHeight: true
                                            spacing: 4
                                            TextInput {
                                                text: root.policyUrl.toString().replace("file:///", "")
                                                placeholderText: "Select a policy package"
                                                readOnly: true
                                                enabled: Session.projectOpen
                                            }
                                            IconButton {
                                                iconSource: Theme.icon("open")
                                                toolTip: "Select policy package"
                                                buttonSize: Theme.controlHeight
                                                enabled: Session.projectOpen
                                                onClicked: {
                                                    root.selectedAsset = "policy"
                                                    assetDialog.open()
                                                }
                                            }
                                        }
                                    }
                                    PropertyRow {
                                        label: "Inference adapter"
                                        SelectField {
                                            enabled: Session.projectOpen
                                            model: ["PyTorch", "JAX", "ONNX Runtime"]
                                            placeholderText: "Select adapter"
                                        }
                                    }
                                    PropertyRow {
                                        label: "Training interface"
                                        SelectField {
                                            enabled: Session.projectOpen
                                            model: ["Inference only", "Behavior cloning", "LoRA trainer", "Custom trainer plugin"]
                                            placeholderText: "Select supported interface"
                                        }
                                    }
                                }

                                Section {
                                    title: "Physical System"
                                    summary: "Vehicle or robot configuration"

                                    PropertyRow {
                                        label: "Configuration"
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Layout.fillHeight: true
                                            spacing: 4
                                            TextInput {
                                                text: root.vehicleConfigUrl.toString().replace("file:///", "")
                                                placeholderText: "Select vehicle or robot configuration"
                                                readOnly: true
                                                enabled: Session.projectOpen
                                            }
                                            IconButton {
                                                iconSource: Theme.icon("open")
                                                toolTip: "Select physical-system configuration"
                                                buttonSize: Theme.controlHeight
                                                enabled: Session.projectOpen
                                                onClicked: {
                                                    root.selectedAsset = "vehicle"
                                                    assetDialog.open()
                                                }
                                            }
                                        }
                                    }
                                    PropertyRow {
                                        label: "Dynamics adapter"
                                        SelectField {
                                            enabled: Session.projectOpen
                                            model: ["Native deterministic", "CARLA", "MuJoCo", "ROS 2 bridge"]
                                            placeholderText: "Select dynamics adapter"
                                        }
                                    }
                                    PropertyRow {
                                        label: "Control limits"
                                        TextInput { placeholderText: "Acceleration, braking, steering"; enabled: Session.projectOpen }
                                    }
                                }

                                Section {
                                    title: "Sensor Rig"
                                    summary: "Camera, LiDAR, radar, IMU, and pose"

                                    PropertyRow {
                                        label: "Calibration bundle"
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Layout.fillHeight: true
                                            spacing: 4
                                            TextInput {
                                                text: root.calibrationUrl.toString().replace("file:///", "")
                                                placeholderText: "Select calibration bundle"
                                                readOnly: true
                                                enabled: Session.projectOpen
                                            }
                                            IconButton {
                                                iconSource: Theme.icon("open")
                                                toolTip: "Select sensor calibration"
                                                buttonSize: Theme.controlHeight
                                                enabled: Session.projectOpen
                                                onClicked: {
                                                    root.selectedAsset = "calibration"
                                                    assetDialog.open()
                                                }
                                            }
                                        }
                                    }
                                    PropertyRow {
                                        label: "Synchronization"
                                        SelectField {
                                            enabled: Session.projectOpen
                                            model: ["Timestamp interpolation", "Frame lock", "External clock"]
                                            placeholderText: "Select synchronization"
                                        }
                                    }
                                    PropertyRow {
                                        label: "Virtual sensors"
                                        TextInput { placeholderText: "Published by sensor adapter"; readOnly: true; enabled: false }
                                    }
                                }

                                Section {
                                    title: "Recording Source"
                                    summary: Session.recordingSelected ? Session.recordingName : "No recording selected"

                                    PropertyRow {
                                        label: "Recording"
                                        TextInput {
                                            text: Session.recordingUrl.toString().replace("file:///", "")
                                            placeholderText: "Select camera, MCAP, or ROS bag recording"
                                            readOnly: true
                                            enabled: Session.projectOpen
                                        }
                                    }
                                    PropertyRow {
                                        label: "Pose / telemetry"
                                        TextInput { placeholderText: "Optional synchronized telemetry source"; enabled: Session.projectOpen }
                                    }
                                    PropertyRow {
                                        label: "Time range"
                                        TextInput { placeholderText: "Use full recording"; enabled: Session.recordingSelected }
                                    }
                                }

                                Section {
                                    title: "World Compiler"
                                    summary: "Appearance, geometry, actors, road graph, uncertainty"

                                    PropertyRow {
                                        label: "Appearance"
                                        SelectField {
                                            enabled: Session.recordingSelected
                                            model: ["Gaussian reconstruction", "Recorded imagery", "Geometry only"]
                                            placeholderText: "Select rendering source"
                                        }
                                    }
                                    PropertyRow {
                                        label: "Physics"
                                        SelectField {
                                            enabled: Session.recordingSelected
                                            model: ["Deterministic geometry", "CARLA", "MuJoCo"]
                                            placeholderText: "Select physics adapter"
                                        }
                                    }
                                    PropertyRow {
                                        label: "Output directory"
                                        TextInput { placeholderText: "Choose build output"; enabled: Session.projectOpen }
                                    }
                                }
                            }
                        }
                    }
                }

                BottomDrawer {
                    SplitView.preferredHeight: implicitHeight
                    SplitView.minimumHeight: 34
                    SplitView.maximumHeight: 220
                }
            }

            Panel {
                SplitView.preferredWidth: 300
                SplitView.minimumWidth: 260
                SplitView.maximumWidth: 420

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Readiness"
                        subtitle: "Not evaluated"
                        iconSource: Theme.icon("verify")
                        Layout.fillWidth: true
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.margins: 12
                        spacing: 4

                        Repeater {
                            model: [
                                "Policy adapter",
                                "Physical system",
                                "Sensor calibration",
                                "Recording source",
                                "World compiler",
                                "Test plan"
                            ]

                            delegate: Rectangle {
                                id: readinessRow
                                required property string modelData
                                Layout.fillWidth: true
                                Layout.preferredHeight: 48
                                color: "transparent"
                                border.width: 0

                                RowLayout {
                                    anchors.fill: parent
                                    spacing: 9

                                    SvgIcon { source: Theme.icon("info"); iconSize: 16; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        Text { text: readinessRow.modelData; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 11 }
                                        Text { text: "Not checked"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9 }
                                    }
                                }
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.borderSoft }

                    EmptyState {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        iconSource: Theme.icon("verify")
                        title: "Readiness has not run"
                        description: "Checks will use the connected adapters and compiler. No pass state is inferred from form values."
                    }
                }
            }
        }
    }

    FileDialog {
        id: assetDialog
        title: "Select Configuration Asset"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Configuration files (*.json *.yaml *.yml *.toml *.onnx *.pt)", "All files (*)"]
        onAccepted: {
            if (root.selectedAsset === "policy") root.policyUrl = selectedFile
            else if (root.selectedAsset === "vehicle") root.vehicleConfigUrl = selectedFile
            else if (root.selectedAsset === "calibration") root.calibrationUrl = selectedFile
        }
    }
}
