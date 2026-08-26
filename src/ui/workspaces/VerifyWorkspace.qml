import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../components"

Item {
    id: root

    // Real availability: verification stages run inside the campaign engine.
    readonly property bool verifierAvailable: RealityCIController.online
    readonly property var examPayload: RealityCIController.latestPayload("HIDDEN_EXAM_COMPLETED")
    readonly property var regressionPayload: RealityCIController.latestPayload("REGRESSION_COMPLETED")
    readonly property var promotedPayload: RealityCIController.latestPayload("CHECKPOINT_PROMOTED")
    readonly property var rejectedPayload: RealityCIController.latestPayload("CHECKPOINT_REJECTED")
    readonly property var checkpointPayload: RealityCIController.latestPayload("CHECKPOINT_READY")
    readonly property var debtPayload: RealityCIController.latestPayload("REALITY_DEBT_UPDATED")
    readonly property bool decisionMade: Object.keys(root.promotedPayload).length > 0
                                          || Object.keys(root.rejectedPayload).length > 0
    readonly property bool promoted: Object.keys(root.promotedPayload).length > 0

    property var examRows: []
    property var failedCheckRows: []

    function rebuildFromEvents() {
        const nextExamRows = []
        if (root.examPayload.exam_id !== undefined) {
            nextExamRows.push({
                capability: "occluded-pedestrian-crossing/v1",
                scenarios: String(root.examPayload.exam_id),
                baseline: (Number(root.examPayload.baseline_success) * 100).toFixed(1) + "%",
                candidate: (Number(root.examPayload.candidate_success) * 100).toFixed(1) + "%"
            })
        }
        root.examRows = nextExamRows

        const decision = root.promoted ? root.promotedPayload : root.rejectedPayload
        const nextFailedRows = []
        if (decision.failed_checks !== undefined) {
            const checks = decision.failed_checks
            for (let i = 0; i < checks.length; ++i)
                nextFailedRows.push({ check: String(checks[i]) })
        }
        root.failedCheckRows = nextFailedRows
    }

    Connections {
        target: RealityCIController
        function onEventsChanged() { root.rebuildFromEvents() }
    }
    Component.onCompleted: rebuildFromEvents()

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "Verify"
            subtitle: "Hidden examination, regression gates, checkpoint comparison, and promotion policy"
            helpText: "The candidate faces a hidden exam (vault opened only here) plus protected regression suites. The promotion gate is pure code: target success, confidence floor, no regressions, verified hashes."
            iconSource: Theme.icon("verify")
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
                text: "Run Hidden Exam"
                iconSource: Theme.icon("play")
                tone: "primary"
                enabled: root.verifierAvailable && !RealityCIController.busy
                         && RealityCIController.hasCampaign && !RealityCIController.terminal
                toolTip: root.verifierAvailable
                         ? "Advance the campaign into the hidden exam stage"
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
                SplitView.preferredWidth: 320
                SplitView.minimumWidth: 270
                SplitView.maximumWidth: 450

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Hidden Exam Results"
                        subtitle: root.examPayload.exam_id !== undefined
                                  ? String(root.examPayload.exam_id)
                                  : "No exam committed"
                        iconSource: Theme.icon("verify")
                        Layout.fillWidth: true
                    }

                    RecordTable {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.topMargin: 6
                        rows: root.examRows
                        columns: [
                            { title: "CAPABILITY", field: "capability", width: 200 },
                            { title: "EXAM", field: "scenarios", width: 130 },
                            { title: "BASELINE", field: "baseline", width: 84 },
                            { title: "CANDIDATE", field: "candidate", width: 90 }
                        ]
                        emptyIcon: Theme.icon("verify")
                        emptyTitle: "No hidden-exam results"
                        emptyDescription: "Held-out results appear after the examiner commits an exam record on seeds sealed before training."
                    }

                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.borderSoft }

                    Section {
                        title: "Generalization"
                        Layout.fillWidth: true
                        PropertyRow {
                            label: "Interval"
                            labelWidth: 104
                            TextInput {
                                readOnly: true
                                placeholderText: root.examPayload.interval === undefined
                                                 ? "Not evaluated"
                                                 : "95% CI " + (Number(root.examPayload.interval[0]) * 100).toFixed(1)
                                                   + "%–" + (Number(root.examPayload.interval[1]) * 100).toFixed(1) + "%"
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
                    SplitView.minimumHeight: 180

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Regression Protection"
                            subtitle: root.regressionPayload.regression_id !== undefined
                                      ? String(root.regressionPayload.suites) + " protected suites rerun"
                                      : "Not evaluated"
                            iconSource: Theme.icon("table")
                            Layout.fillWidth: true
                        }

                        Section {
                            title: "Protected Capabilities"
                            Layout.fillWidth: true
                            PropertyRow {
                                label: "Suites"
                                labelWidth: 104
                                TextInput { readOnly: true; placeholderText: root.regressionPayload.suites === undefined ? "None configured" : String(root.regressionPayload.suites) }
                            }
                            PropertyRow {
                                label: "Max drop"
                                labelWidth: 104
                                TextInput { readOnly: true; placeholderText: root.regressionPayload.max_drop_pp === undefined ? "Not evaluated" : String(root.regressionPayload.max_drop_pp) + " pp" }
                            }
                            PropertyRow {
                                label: "Policy"
                                labelWidth: 104
                                TextInput { readOnly: true; placeholderText: "deterministic thresholds - an LLM cannot waive these gates" }
                            }
                        }

                        Item { Layout.fillHeight: true }
                    }
                }

                Panel {
                    SplitView.preferredHeight: 220
                    SplitView.minimumHeight: 150
                    SplitView.maximumHeight: 340

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Decision Record"
                            subtitle: !root.decisionMade
                                      ? "Gate not evaluated"
                                      : (root.promoted ? "PROMOTED" : "REJECTED")
                            iconSource: Theme.icon("check")
                            Layout.fillWidth: true
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.margins: 8
                            spacing: 8

                            StatusBadge {
                                text: !root.decisionMade
                                      ? RealityCIController.campaignState
                                      : (root.promoted ? "promoted by code" : "rejected by code")
                                tone: !root.decisionMade ? "neutral"
                                      : (root.promoted ? "success" : "error")
                            }
                        }

                        RecordTable {
                            id: failedChecksTable
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            rows: root.failedCheckRows
                            columns: [
                                { title: "FAILED CHECK", field: "check", width: 420 }
                            ]
                            emptyTitle: root.decisionMade ? "All deterministic checks passed" : "No decision yet"
                            emptyDescription: "The gate evaluates target success, confidence floor, regressions, hashes, and isolation receipts."
                            emptyIcon: Theme.icon("check")
                        }
                    }
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
                        subtitle: !root.decisionMade ? "Not evaluated" : "Decision recorded"
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
                                PropertyRow {
                                    label: "Baseline"
                                    labelWidth: 104
                                    TextInput { readOnly: true; placeholderText: String(root.checkpointPayload.parent_sha256) }
                                }
                                PropertyRow {
                                    label: "Candidate"
                                    labelWidth: 104
                                    TextInput { readOnly: true; placeholderText: String(root.checkpointPayload.candidate_sha256) }
                                }
                            }

                            Section {
                                title: "Reality Debt"
                                PropertyRow {
                                    label: "Total debt"
                                    labelWidth: 104
                                    TextInput {
                                        readOnly: true
                                        placeholderText: root.debtPayload.total_debt === undefined
                                                         ? "Not computed"
                                                         : Number(root.debtPayload.total_debt).toFixed(3)
                                    }
                                }
                            }

                            Section {
                                title: "Decision Provenance"
                                PropertyRow {
                                    label: "Decision ID"
                                    labelWidth: 104
                                    TextInput {
                                        readOnly: true
                                        placeholderText: root.promotedPayload.decision_id !== undefined
                                                         ? String(root.promotedPayload.decision_id)
                                                         : (root.rejectedPayload.decision_id !== undefined
                                                            ? String(root.rejectedPayload.decision_id)
                                                            : "None")
                                    }
                                }
                                PropertyRow {
                                    label: "Authority"
                                    labelWidth: 104
                                    TextInput { readOnly: true; placeholderText: "deterministic code - not an LLM opinion" }
                                }
                            }

                            Text {
                                width: parent.width - 24
                                leftPadding: 12
                                bottomPadding: 12
                                text: "Promote/Reject buttons are intentionally absent: humans cannot override the deterministic gate in either direction."
                                color: Theme.textMuted
                                font.family: Theme.uiFont
                                font.pixelSize: 9
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }
                }
            }
        }
    }
}
