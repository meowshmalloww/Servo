import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../components"

Item {
    id: root

    readonly property bool verifierAvailable: false
    property var baselineSeries: []
    property var candidateSeries: []

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "Verify"
            subtitle: "Hidden examination, regression gates, checkpoint comparison, and promotion policy"
            iconSource: Theme.icon("verify")
            Layout.fillWidth: true

            TextButton { text: "Export Report"; iconSource: Theme.icon("export"); enabled: false }
            TextButton {
                text: "Run Hidden Exam"
                iconSource: Theme.icon("play")
                tone: "primary"
                enabled: false
                toolTip: root.verifierAvailable ? "Evaluate selected checkpoint" : "Verification service is not connected"
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: SplitHandle { }

            Panel {
                SplitView.preferredWidth: 320
                SplitView.minimumWidth: 270
                SplitView.maximumWidth: 450

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Checkpoints"
                        subtitle: Session.checkpointModel === null ? "No model" : "Connected"
                        iconSource: Theme.icon("verify")
                        Layout.fillWidth: true
                    }

                    SearchField {
                        Layout.fillWidth: true
                        Layout.leftMargin: 7
                        Layout.rightMargin: 7
                        Layout.topMargin: 7
                        Layout.bottomMargin: 6
                        hint: "Search checkpoints"
                    }

                    DataTable {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: Session.checkpointModel
                        columns: [
                            { title: "CHECKPOINT", width: 132 },
                            { title: "SOURCE", width: 104 },
                            { title: "GATE", width: 82 }
                        ]
                        emptyIcon: Theme.icon("verify")
                        emptyTitle: "No checkpoints"
                        emptyDescription: "Committed candidate and baseline checkpoints appear after an adapter publishes artifact metadata."
                    }
                }
            }

            SplitView {
                orientation: Qt.Vertical
                SplitView.fillWidth: true
                SplitView.minimumWidth: 680
                handle: SplitHandle { }

                Item {
                    SplitView.preferredHeight: 270
                    SplitView.minimumHeight: 210
                    SplitView.maximumHeight: 390

                    RowLayout {
                        anchors.fill: parent
                        spacing: 4

                        LinePlot {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            title: "Baseline"
                            unit: "selected verification metric"
                            values: root.baselineSeries
                            minimum: 0
                            maximum: 1
                            lineColor: Theme.textSecondary
                        }

                        LinePlot {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            title: "Candidate"
                            unit: "selected verification metric"
                            values: root.candidateSeries
                            minimum: 0
                            maximum: 1
                        }
                    }
                }

                Panel {
                    SplitView.fillHeight: true
                    SplitView.minimumHeight: 240

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Hidden Exam Results"
                            subtitle: "No exam selected"
                            iconSource: Theme.icon("table")
                            Layout.fillWidth: true
                        }

                        DataTable {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            model: null
                            columns: [
                                { title: "CAPABILITY", width: 210 },
                                { title: "SCENARIOS", width: 100 },
                                { title: "BASELINE", width: 104 },
                                { title: "CANDIDATE", width: 104 },
                                { title: "GATE", width: 88 }
                            ]
                            emptyIcon: Theme.icon("verify")
                            emptyTitle: "No hidden-exam results"
                            emptyDescription: "Held-out results remain empty until the verifier commits an exam record."
                        }
                    }
                }

                BottomDrawer {
                    SplitView.preferredHeight: implicitHeight
                    SplitView.minimumHeight: 34
                    SplitView.maximumHeight: 220
                    tabs: ["Exam Output", "Regression", "Artifacts"]
                }
            }

            Panel {
                SplitView.preferredWidth: 350
                SplitView.minimumWidth: 305
                SplitView.maximumWidth: 485

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Promotion Gate"
                        subtitle: "Not evaluated"
                        iconSource: Theme.icon("settings")
                        Layout.fillWidth: true
                    }

                    ScrollView {
                        id: gateScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        Column {
                            width: gateScroll.availableWidth

                            Section {
                                title: "Selection"
                                PropertyRow { label: "Baseline"; labelWidth: 104; TextInput { placeholderText: "No baseline selected"; readOnly: true } }
                                PropertyRow { label: "Candidate"; labelWidth: 104; TextInput { placeholderText: "No candidate selected"; readOnly: true } }
                                PropertyRow { label: "Exam suite"; labelWidth: 104; TextInput { placeholderText: "No hidden suite"; readOnly: true } }
                            }

                            Section {
                                title: "Generalization"
                                PropertyRow { label: "Result"; labelWidth: 104; TextInput { placeholderText: "Not evaluated"; readOnly: true } }
                                PropertyRow { label: "Coverage"; labelWidth: 104; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "Threshold"; labelWidth: 104; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                            }

                            Section {
                                title: "Regression"
                                PropertyRow { label: "Protected sets"; labelWidth: 104; TextInput { placeholderText: "None configured"; readOnly: true } }
                                PropertyRow { label: "Regressions"; labelWidth: 104; TextInput { placeholderText: "Not evaluated"; readOnly: true } }
                                PropertyRow { label: "Policy"; labelWidth: 104; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                            }

                            Section {
                                title: "Reality Debt"
                                PropertyRow { label: "Before"; labelWidth: 104; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "After"; labelWidth: 104; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "Delta"; labelWidth: 104; TextInput { placeholderText: "Not computed"; readOnly: true } }
                            }

                            Section {
                                title: "Decision Record"
                                PropertyRow { label: "Gate state"; labelWidth: 104; TextInput { placeholderText: "Not evaluated"; readOnly: true } }
                                PropertyRow { label: "Exam artifact"; labelWidth: 104; TextInput { placeholderText: "None"; readOnly: true } }
                                PropertyRow { label: "Provenance"; labelWidth: 104; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.borderSoft }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.margins: 8
                        spacing: 6
                        TextButton { text: "Reject"; tone: "danger"; enabled: false; Layout.fillWidth: true }
                        TextButton { text: "Promote"; iconSource: Theme.icon("check"); tone: "primary"; enabled: false; Layout.fillWidth: true }
                    }
                }
            }
        }
    }
}
