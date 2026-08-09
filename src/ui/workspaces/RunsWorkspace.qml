import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../components"

Item {
    id: root

    readonly property bool runnerAvailable: false
    property var detectionSeries: []
    property var speedSeries: []

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "Runs"
            subtitle: "Execute the connected policy in deterministic worlds and collect synchronized evidence"
            iconSource: Theme.icon("run")
            Layout.fillWidth: true

            IconButton { iconSource: Theme.icon("pause"); toolTip: "Pause run"; enabled: false }
            IconButton { iconSource: Theme.icon("stop"); toolTip: "Stop run"; enabled: false }

            TextButton {
                text: "Start Run"
                iconSource: Theme.icon("play")
                tone: "primary"
                enabled: Session.projectOpen && Session.worldModel !== null && root.runnerAvailable
                toolTip: root.runnerAvailable ? "Start policy execution" : "Run service is not connected"
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: SplitHandle { }

            Panel {
                SplitView.preferredWidth: 320
                SplitView.minimumWidth: 260
                SplitView.maximumWidth: 440

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Run History"
                        subtitle: Session.runModel === null ? "No model" : "Connected"
                        iconSource: Theme.icon("table")
                        Layout.fillWidth: true
                    }

                    SearchField {
                        Layout.fillWidth: true
                        Layout.leftMargin: 7
                        Layout.rightMargin: 7
                        Layout.topMargin: 7
                        Layout.bottomMargin: 6
                        hint: "Search runs"
                    }

                    DataTable {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: Session.runModel
                        columns: [
                            { title: "RUN", width: 92 },
                            { title: "WORLD", width: 128 },
                            { title: "STATE", width: 82 }
                        ]
                        emptyIcon: Theme.icon("run")
                        emptyTitle: "No policy runs"
                        emptyDescription: "Runs appear only after a connected runner publishes durable execution records."
                    }
                }
            }

            SplitView {
                orientation: Qt.Vertical
                SplitView.fillWidth: true
                SplitView.minimumWidth: 620
                handle: SplitHandle { }

                ViewportSurface {
                    SplitView.fillHeight: true
                    SplitView.minimumHeight: 300
                    title: "Sensor View"
                    available: false
                    emptyTitle: "No run selected"
                    emptyDescription: "Select a recorded execution to inspect synchronized sensor frames and policy state."
                }

                Timeline {
                    SplitView.preferredHeight: 112
                    SplitView.minimumHeight: 86
                    SplitView.maximumHeight: 180
                    available: false
                }

                Item {
                    SplitView.preferredHeight: 190
                    SplitView.minimumHeight: 150
                    SplitView.maximumHeight: 280

                    RowLayout {
                        anchors.fill: parent
                        spacing: 4

                        LinePlot {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            title: "Detection Confidence"
                            unit: "policy telemetry"
                            values: root.detectionSeries
                            minimum: 0
                            maximum: 1
                        }

                        LinePlot {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            title: "Ego Speed"
                            unit: "m/s"
                            values: root.speedSeries
                            minimum: 0
                            maximum: 1
                            lineColor: Theme.textSecondary
                        }
                    }
                }
            }

            Panel {
                SplitView.preferredWidth: 310
                SplitView.minimumWidth: 270
                SplitView.maximumWidth: 430

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Run Inspector"
                        subtitle: "No selection"
                        iconSource: Theme.icon("settings")
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
                                title: "Execution"
                                PropertyRow { label: "Run ID"; labelWidth: 90; TextInput { placeholderText: "No selection"; readOnly: true } }
                                PropertyRow { label: "State"; labelWidth: 90; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "World"; labelWidth: 90; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "Policy"; labelWidth: 90; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                            }

                            Section {
                                title: "Evidence"
                                PropertyRow { label: "Frames"; labelWidth: 90; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "Telemetry"; labelWidth: 90; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "Model output"; labelWidth: 90; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "Trajectory"; labelWidth: 90; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                            }

                            Section {
                                title: "Outcome"
                                PropertyRow { label: "Result"; labelWidth: 90; TextInput { placeholderText: "Not evaluated"; readOnly: true } }
                                PropertyRow { label: "Collision"; labelWidth: 90; TextInput { placeholderText: "Not evaluated"; readOnly: true } }
                                PropertyRow { label: "Artifacts"; labelWidth: 90; TextInput { placeholderText: "None"; readOnly: true } }
                            }
                        }
                    }
                }
            }
        }
    }
}
