import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../components"

Item {
    id: root

    // Live availability mirrors the control API connection state.
    readonly property bool diagnosisServiceAvailable: RealityCIController.online
    readonly property var proposalPayload: RealityCIController.latestPayload("HYPOTHESES_PROPOSED")
    readonly property var failurePayload: RealityCIController.latestPayload("FAILURE_DETECTED")
    readonly property var rootCausePayload: RealityCIController.latestPayload("ROOT_CAUSE_ESTABLISHED")
    readonly property var inconclusivePayload: RealityCIController.latestPayload("ROOT_CAUSE_INCONCLUSIVE")
    readonly property bool causeEstablished: Object.keys(rootCausePayload).length > 0
    property var hypothesisRows: []
    property var experimentRows: []

    function rebuildFromEvents() {
        const nextHypothesisRows = []
        const hypotheses = root.proposalPayload.hypotheses === undefined
                           ? [] : root.proposalPayload.hypotheses
        for (let i = 0; i < hypotheses.length; ++i) {
            nextHypothesisRows.push({
                kind: String(hypotheses[i].kind),
                claim: String(hypotheses[i].claim),
                id: String(hypotheses[i].hypothesis_id)
            })
        }
        root.hypothesisRows = nextHypothesisRows

        const nextExperimentRows = []
        const completed = RealityCIController.payloadsOf("EXPERIMENT_COMPLETED")
        for (let j = 0; j < completed.length; ++j) {
            nextExperimentRows.push({
                sequence: completed[j].sequence,
                intervention: String(completed[j].intervention),
                outcome: String(completed[j].outcome),
                scenario: String(completed[j].derived_scenario_id)
            })
        }
        root.experimentRows = nextExperimentRows
    }

    Connections {
        target: RealityCIController
        function onEventsChanged() { root.rebuildFromEvents() }
        function onConnectionStateChanged() { if (!RealityCIController.online) root.rebuildFromEvents() }
    }
    Component.onCompleted: rebuildFromEvents()

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "Diagnose"
            subtitle: "Failure evidence, causal hypotheses, and counterfactual experiments"
            helpText: "Inspect the failure timeline, ranked hypotheses from the Diagnostician, and executed counterfactual experiments. Root cause is established by code from intervention outcomes - never by an LLM opinion."
            iconSource: Theme.icon("diagnose")
            Layout.fillWidth: true

            StatusBadge {
                text: RealityCIController.connectionState
                tone: RealityCIController.online ? "success"
                      : RealityCIController.connectionState === "error" ? "error" : "neutral"
                Layout.alignment: Qt.AlignVCenter
            }

            IconButton {
                iconSource: Theme.icon("refresh")
                toolTip: "Reconnect and reload records"
                enabled: !RealityCIController.busy
                onClicked: RealityCIController.connectToServer()
            }

            TextButton {
                text: "Run Experiments"
                iconSource: Theme.icon("play")
                tone: "primary"
                enabled: root.diagnosisServiceAvailable && !RealityCIController.busy
                         && RealityCIController.hasCampaign && !RealityCIController.terminal
                toolTip: root.diagnosisServiceAvailable
                         ? "Advance the campaign into the counterfactual experiment stage"
                         : "Control API is not connected"
                onClicked: RealityCIController.stepCampaign()
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
                        title: "Failure Record"
                        subtitle: Object.keys(root.failurePayload).length > 0
                                  ? String(root.failurePayload.failure_id)
                                  : "No failure in the loaded campaign"
                        iconSource: Theme.icon("diagnose")
                        Layout.fillWidth: true
                    }

                    ScrollView {
                        id: failureScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        Column {
                            width: failureScroll.availableWidth

                            Section {
                                title: "Detected Failure"
                                visible: Object.keys(root.failurePayload).length > 0
                                PropertyRow { label: "Class"; labelWidth: 102; TextInput { readOnly: true; placeholderText: String(root.failurePayload.failure_class) } }
                                PropertyRow { label: "Severity"; labelWidth: 102; TextInput { readOnly: true; placeholderText: String(root.failurePayload.severity) } }
                                PropertyRow { label: "Record"; labelWidth: 102; TextInput { readOnly: true; placeholderText: String(root.failurePayload.failure_id) } }
                            }

                            Section {
                                title: "Diagnostician"
                                visible: root.proposalPayload.diagnostician !== undefined
                                PropertyRow { label: "Service"; labelWidth: 102; TextInput { readOnly: true; placeholderText: String(root.proposalPayload.diagnostician) } }
                                PropertyRow { label: "Model"; labelWidth: 102; TextInput { readOnly: true; placeholderText: String(root.proposalPayload.model_id) } }
                                PropertyRow { label: "Prompt ver."; labelWidth: 102; TextInput { readOnly: true; placeholderText: String(root.proposalPayload.prompt_template_version) } }
                            }

                            EmptyState {
                                width: parent.width
                                height: 180
                                visible: Object.keys(root.failurePayload).length === 0
                                iconSource: Theme.icon("diagnose")
                                title: "No failure evidence"
                                description: "Detected failures appear only after a connected campaign publishes an evidence bundle."
                            }
                        }
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
                    SplitView.minimumHeight: 200

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Ranked Hypotheses"
                            subtitle: root.hypothesisRows.length > 0
                                      ? "Proposed by " + root.proposalPayload.diagnostician
                                      : "No causal proposal published"
                            iconSource: Theme.icon("search")
                            Layout.fillWidth: true
                        }

                        RecordTable {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            rows: root.hypothesisRows
                            columns: [
                                { title: "KIND", field: "kind", width: 150 },
                                { title: "CLAIM", field: "claim", width: 420 },
                                { title: "ID", field: "id", width: 130 }
                            ]
                            emptyIcon: Theme.icon("diagnose")
                            emptyTitle: "No hypotheses"
                            emptyDescription: "A connected Diagnostician publishes ranked hypotheses after a failure record exists."
                        }
                    }
                }

                Panel {
                    SplitView.preferredHeight: 240
                    SplitView.minimumHeight: 170
                    SplitView.maximumHeight: 380

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Counterfactual Experiments"
                            subtitle: root.experimentRows.length > 0
                                      ? root.experimentRows.length + " executed interventions"
                                      : "No experiments executed"
                            iconSource: Theme.icon("table")
                            Layout.fillWidth: true
                        }

                        RecordTable {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            rows: root.experimentRows
                            columns: [
                                { title: "SEQ", field: "sequence", width: 52 },
                                { title: "INTERVENTION", field: "intervention", width: 230 },
                                { title: "OUTCOME", field: "outcome", width: 140 },
                                { title: "DERIVED SCENARIO", field: "scenario", width: 260 }
                            ]
                            emptyIcon: Theme.icon("diagnose")
                            emptyTitle: "No experiments"
                            emptyDescription: "Executed counterfactuals appear here with their measured outcomes."
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
                        subtitle: root.causeEstablished ? "Established by deterministic gate" : "No selection"
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
                                title: "Causal Conclusion"

                                Item {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: root.causeEstablished ? 120 : 160

                                    EmptyState {
                                        anchors.fill: parent
                                        visible: !root.causeEstablished
                                        iconSource: Theme.icon("info")
                                        title: root.inconclusivePayload.satisfied !== undefined
                                               ? "Inconclusive - more evidence scheduled"
                                               : "Not established"
                                        description: "Servo reports a root cause only when executed interventions support it."
                                    }

                                    ColumnLayout {
                                        anchors.fill: parent
                                        visible: root.causeEstablished
                                        spacing: 4

                                        StatusBadge {
                                            text: String(root.rootCausePayload.root_cause)
                                            tone: "success"
                                        }
                                        PropertyRow { label: "Rule"; labelWidth: 102; TextInput { readOnly: true; placeholderText: String(root.rootCausePayload.rule) } }
                                        PropertyRow { label: "Diagnosis"; labelWidth: 102; TextInput { readOnly: true; placeholderText: String(root.rootCausePayload.diagnosis_id) } }
                                    }
                                }
                            }

                            Section {
                                title: "Evidence Contract"
                                PropertyRow {
                                    label: "Interventions"
                                    labelWidth: 102
                                    TextInput { readOnly: true; placeholderText: String(root.experimentRows.length) + " executed" }
                                }
                                PropertyRow {
                                    label: "Response hash"
                                    labelWidth: 102
                                    TextInput { readOnly: true; placeholderText: root.proposalPayload.response_sha256 === undefined ? "None" : String(root.proposalPayload.response_sha256) }
                                }
                                PropertyRow {
                                    label: "Provenance"
                                    labelWidth: 102
                                    TextInput { readOnly: true; placeholderText: "deterministic gate over outcomes only" }
                                }
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.borderSoft }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.margins: 8
                        spacing: 6
                        TextButton {
                            text: "Create Experience Plan"
                            iconSource: Theme.icon("plus")
                            enabled: root.causeEstablished && !RealityCIController.busy
                                     && RealityCIController.hasCampaign && !RealityCIController.terminal
                            Layout.fillWidth: true
                            onClicked: RealityCIController.stepCampaign()
                        }
                    }
                }
            }
        }
    }
}
