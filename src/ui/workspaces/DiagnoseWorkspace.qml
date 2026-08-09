import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../components"

Item {
    id: root

    readonly property bool diagnosisServiceAvailable: false

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "Diagnose"
            subtitle: "Failure evidence, causal hypotheses, and counterfactual experiments"
            iconSource: Theme.icon("diagnose")
            Layout.fillWidth: true

            TextButton {
                text: "Run Experiments"
                iconSource: Theme.icon("play")
                tone: "primary"
                enabled: false
                toolTip: root.diagnosisServiceAvailable
                         ? "Execute selected counterfactual experiments"
                         : "Causal experiment service is not connected"
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: SplitHandle { }

            Panel {
                SplitView.preferredWidth: 310
                SplitView.minimumWidth: 260
                SplitView.maximumWidth: 440

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Failure Queue"
                        subtitle: Session.failureModel === null ? "No model" : "Connected"
                        iconSource: Theme.icon("diagnose")
                        Layout.fillWidth: true
                    }

                    SearchField {
                        Layout.fillWidth: true
                        Layout.leftMargin: 7
                        Layout.rightMargin: 7
                        Layout.topMargin: 7
                        Layout.bottomMargin: 6
                        hint: "Search failures"
                    }

                    DataTable {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: Session.failureModel
                        columns: [
                            { title: "FAILURE", width: 116 },
                            { title: "RUN", width: 84 },
                            { title: "STATE", width: 86 }
                        ]
                        emptyIcon: Theme.icon("diagnose")
                        emptyTitle: "No failure evidence"
                        emptyDescription: "Detected failures appear only after an evaluator publishes an evidence bundle for a durable run."
                    }
                }
            }

            SplitView {
                orientation: Qt.Vertical
                SplitView.fillWidth: true
                SplitView.minimumWidth: 660
                handle: SplitHandle { }

                ViewportSurface {
                    SplitView.fillHeight: true
                    SplitView.minimumHeight: 250
                    title: "Failure Evidence"
                    available: false
                    emptyTitle: "No failure selected"
                    emptyDescription: "Select a failure to inspect synchronized sensor evidence, policy outputs, and executed trajectory."
                }

                Timeline {
                    SplitView.preferredHeight: 108
                    SplitView.minimumHeight: 84
                    SplitView.maximumHeight: 165
                    available: false
                }

                Panel {
                    SplitView.preferredHeight: 220
                    SplitView.minimumHeight: 160
                    SplitView.maximumHeight: 330

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Counterfactual Experiments"
                            subtitle: Session.experimentModel === null ? "No model" : "Connected"
                            iconSource: Theme.icon("table")
                            Layout.fillWidth: true
                        }

                        DataTable {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            model: Session.experimentModel
                            columns: [
                                { title: "INTERVENTION", width: 230 },
                                { title: "TARGET", width: 150 },
                                { title: "DELTA", width: 90 },
                                { title: "OUTCOME", width: 130 }
                            ]
                            emptyIcon: Theme.icon("diagnose")
                            emptyTitle: "No experiments"
                            emptyDescription: "A hypothesis adapter can publish interventions after a failure is selected."
                        }
                    }
                }
            }

            Panel {
                SplitView.preferredWidth: 350
                SplitView.minimumWidth: 300
                SplitView.maximumWidth: 480

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Causal Inspector"
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
                                title: "Failure"
                                PropertyRow { label: "Failure ID"; labelWidth: 102; TextInput { placeholderText: "No selection"; readOnly: true } }
                                PropertyRow { label: "Run"; labelWidth: 102; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "Event time"; labelWidth: 102; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "Evaluator"; labelWidth: 102; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                            }

                            Section {
                                title: "Hypotheses"
                                summary: "Ranked by evidence"

                                Item {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 210

                                    DataTable {
                                        anchors.fill: parent
                                        model: null
                                        columns: [
                                            { title: "HYPOTHESIS", width: 190 },
                                            { title: "EVIDENCE", width: 104 }
                                        ]
                                        emptyIcon: Theme.icon("diagnose")
                                        emptyTitle: "No hypotheses"
                                        emptyDescription: "No causal proposal has been published."
                                    }
                                }
                            }

                            Section {
                                title: "Causal Conclusion"

                                Item {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 160

                                    EmptyState {
                                        anchors.fill: parent
                                        iconSource: Theme.icon("info")
                                        title: "Not established"
                                        description: "Servo reports a root cause only when interventions support it. Confidence is never inferred from a ranked suggestion alone."
                                    }
                                }
                            }

                            Section {
                                title: "Evidence Contract"
                                PropertyRow { label: "Interventions"; labelWidth: 102; TextInput { placeholderText: "None executed"; readOnly: true } }
                                PropertyRow { label: "Artifacts"; labelWidth: 102; TextInput { placeholderText: "None"; readOnly: true } }
                                PropertyRow { label: "Provenance"; labelWidth: 102; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.borderSoft }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.margins: 8
                        spacing: 6
                        TextButton { text: "Create Experience Plan"; iconSource: Theme.icon("plus"); enabled: false; Layout.fillWidth: true }
                        IconButton { iconSource: Theme.icon("export"); toolTip: "Export evidence"; enabled: false; buttonSize: Theme.controlHeight }
                    }
                }
            }
        }
    }
}
