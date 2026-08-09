import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../components"

Item {
    id: root

    readonly property bool trainerAvailable: false
    property var lossSeries: []
    property var validationSeries: []

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "Train"
            subtitle: "Targeted experience, supported training adapters, artifacts, and durable checkpoints"
            iconSource: Theme.icon("train")
            Layout.fillWidth: true

            IconButton { iconSource: Theme.icon("pause"); toolTip: "Pause training"; enabled: false }
            IconButton { iconSource: Theme.icon("stop"); toolTip: "Stop training"; enabled: false }
            TextButton {
                text: "Start Training"
                iconSource: Theme.icon("play")
                tone: "primary"
                enabled: false
                toolTip: root.trainerAvailable ? "Start configured training job" : "Training adapter is not connected"
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: SplitHandle { }

            Panel {
                SplitView.preferredWidth: 300
                SplitView.minimumWidth: 250
                SplitView.maximumWidth: 420

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Training Jobs"
                        subtitle: Session.trainingJobModel === null ? "No model" : "Connected"
                        iconSource: Theme.icon("train")
                        Layout.fillWidth: true
                    }

                    SearchField {
                        Layout.fillWidth: true
                        Layout.leftMargin: 7
                        Layout.rightMargin: 7
                        Layout.topMargin: 7
                        Layout.bottomMargin: 6
                        hint: "Search jobs"
                    }

                    DataTable {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: Session.trainingJobModel
                        columns: [
                            { title: "JOB", width: 104 },
                            { title: "ADAPTER", width: 108 },
                            { title: "STATE", width: 84 }
                        ]
                        emptyIcon: Theme.icon("train")
                        emptyTitle: "No training jobs"
                        emptyDescription: "Jobs appear only when a supported trainer persists a submitted run."
                    }
                }
            }

            SplitView {
                orientation: Qt.Vertical
                SplitView.fillWidth: true
                SplitView.minimumWidth: 680
                handle: SplitHandle { }

                Item {
                    SplitView.preferredHeight: 250
                    SplitView.minimumHeight: 190
                    SplitView.maximumHeight: 350

                    RowLayout {
                        anchors.fill: parent
                        spacing: 4

                        LinePlot {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            title: "Training Objective"
                            unit: "adapter-defined"
                            values: root.lossSeries
                            minimum: 0
                            maximum: 1
                            lineColor: Theme.textSecondary
                        }

                        LinePlot {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            title: "Validation Metric"
                            unit: "evaluation-defined"
                            values: root.validationSeries
                            minimum: 0
                            maximum: 1
                        }
                    }
                }

                Panel {
                    SplitView.fillHeight: true
                    SplitView.minimumHeight: 180

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Job Output"
                            subtitle: "No selection"
                            iconSource: Theme.icon("table")
                            Layout.fillWidth: true
                        }

                        EmptyState {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            iconSource: Theme.icon("table")
                            title: "No process output"
                            description: "Structured trainer logs stream here after a real job is selected. Servo does not generate placeholder epochs or progress."
                        }
                    }
                }

                Panel {
                    SplitView.preferredHeight: 190
                    SplitView.minimumHeight: 150
                    SplitView.maximumHeight: 270

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Artifacts"
                            subtitle: "Durable outputs"
                            iconSource: Theme.icon("folder")
                            Layout.fillWidth: true
                        }

                        DataTable {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            model: null
                            columns: [
                                { title: "NAME", width: 270 },
                                { title: "TYPE", width: 110 },
                                { title: "SIZE", width: 100 },
                                { title: "CREATED", width: 150 }
                            ]
                            emptyIcon: Theme.icon("folder")
                            emptyTitle: "No artifacts"
                            emptyDescription: "Checkpoints and metrics appear after the trainer publishes committed artifacts."
                        }
                    }
                }
            }

            Panel {
                SplitView.preferredWidth: 340
                SplitView.minimumWidth: 300
                SplitView.maximumWidth: 470

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Training Configuration"
                        subtitle: "Unconfigured"
                        iconSource: Theme.icon("settings")
                        Layout.fillWidth: true
                    }

                    ScrollView {
                        id: configScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        Column {
                            width: configScroll.availableWidth

                            Section {
                                title: "Adapter"
                                summary: "Supported interfaces only"
                                PropertyRow { label: "Base policy"; labelWidth: 100; TextInput { placeholderText: "No policy selected"; readOnly: true } }
                                PropertyRow { label: "Interface"; labelWidth: 100; SelectField { model: ["Behavior cloning", "LoRA trainer", "Custom trainer plugin"]; placeholderText: "Select interface"; enabled: Session.projectOpen } }
                                PropertyRow { label: "Entry point"; labelWidth: 100; TextInput { placeholderText: "Published by adapter"; readOnly: true } }
                            }

                            Section {
                                title: "Experience Dataset"
                                PropertyRow { label: "Dataset"; labelWidth: 100; TextInput { placeholderText: "No dataset selected"; readOnly: true } }
                                PropertyRow { label: "Provenance"; labelWidth: 100; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "Splits"; labelWidth: 100; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                            }

                            Section {
                                title: "Compute"
                                PropertyRow { label: "Executor"; labelWidth: 100; SelectField { model: ["Local adapter", "Remote executor"]; placeholderText: "Select executor"; enabled: Session.projectOpen } }
                                PropertyRow { label: "Precision"; labelWidth: 100; TextInput { placeholderText: "Defined by trainer" } }
                                PropertyRow { label: "Workers"; labelWidth: 100; TextInput { placeholderText: "Defined by executor" } }
                            }

                            Section {
                                title: "Stop Conditions"
                                PropertyRow { label: "Budget"; labelWidth: 100; TextInput { placeholderText: "Epochs, steps, or wall time" } }
                                PropertyRow { label: "Early stop"; labelWidth: 100; TextInput { placeholderText: "Optional adapter rule" } }
                                PropertyRow { label: "Checkpoint"; labelWidth: 100; TextInput { placeholderText: "Artifact cadence" } }
                            }

                            Section {
                                title: "Regression Guard"
                                PropertyRow { label: "Metric"; labelWidth: 100; TextInput { placeholderText: "Select verification metric" } }
                                PropertyRow { label: "Threshold"; labelWidth: 100; TextInput { placeholderText: "No threshold" } }
                                PropertyRow { label: "Action"; labelWidth: 100; SelectField { model: ["Stop job", "Flag checkpoint"]; placeholderText: "Select action" } }
                            }
                        }
                    }
                }
            }
        }
    }
}
