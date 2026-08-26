import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../components"

Item {
    id: root

    // Real availability: the control API must answer /healthz before any
    // campaign action is enabled. Nothing here is simulated.
    readonly property bool runnerAvailable: RealityCIController.online
    property var detectionSeries: []
    property var speedSeries: []
    property int selectedSequence: -1
    readonly property string selectedPayloadJson: {
        const count = RealityCIController.eventCount
        for (let row = 0; row < count; ++row) {
            const event = RealityCIController.eventAt(row)
            if (event.sequence === root.selectedSequence)
                return event.payload_json
        }
        return ""
    }
    readonly property var failurePayload: RealityCIController.latestPayload("FAILURE_DETECTED")
    readonly property var runCompletedPayload: RealityCIController.latestPayload("RUN_COMPLETED")
    readonly property var checkpointPayload: RealityCIController.latestPayload("CHECKPOINT_READY")

    function prettyJson(text) {
        if (text.length === 0)
            return ""
        try {
            return JSON.stringify(JSON.parse(text), null, 2)
        } catch (error) {
            return text
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "Runs"
            subtitle: "Execute the connected policy in deterministic worlds and collect synchronized evidence"
            helpText: "Connect to the RealityCI control API, create a campaign around the baseline checkpoint, then execute it. Every value shown comes from durable backend records; nothing is simulated."
            iconSource: Theme.icon("run")
            Layout.fillWidth: true

            StatusBadge {
                text: RealityCIController.connectionState
                tone: RealityCIController.online ? "success"
                      : RealityCIController.connectionState === "error" ? "error"
                      : RealityCIController.connectionState === "connecting" ? "warning"
                      : "neutral"
                Layout.alignment: Qt.AlignVCenter
            }

            IconButton {
                iconSource: Theme.icon("refresh")
                toolTip: "Reconnect to the control API"
                enabled: !RealityCIController.busy
                onClicked: RealityCIController.connectToServer()
            }

            TextButton {
                text: "Create Campaign"
                iconSource: Theme.icon("plus")
                enabled: root.runnerAvailable && !RealityCIController.busy && !RealityCIController.hasCampaign
                toolTip: RealityCIController.hasCampaign
                         ? "Campaign " + RealityCIController.campaignId + " already exists"
                         : "Create a fail-to-promote campaign around the baseline checkpoint"
                onClicked: RealityCIController.createCampaign(
                               campaignCheckpointField.text,
                               parseInt(campaignScenariosField.text) || 24,
                               parseInt(campaignExamField.text) || 8,
                               parseInt(campaignProtectedField.text) || 4,
                               parseInt(campaignEpochsField.text) || 10,
                               parseFloat(campaignTargetField.text) || 0.9,
                               parseFloat(campaignFloorField.text) || 0.5)
            }

            TextButton {
                text: "New Campaign"
                compact: true
                visible: RealityCIController.hasCampaign
                enabled: root.runnerAvailable && !RealityCIController.busy
                toolTip: "Forget the selected campaign and configure a new one"
                onClicked: RealityCIController.forgetCampaign()
            }

            TextButton {
                text: "Step"
                iconSource: Theme.icon("forward")
                compact: true
                enabled: root.runnerAvailable && !RealityCIController.busy
                         && RealityCIController.hasCampaign && !RealityCIController.terminal
                toolTip: "Execute exactly one workflow step"
                onClicked: RealityCIController.stepCampaign()
            }

            TextButton {
                text: "Start Run"
                iconSource: Theme.icon("play")
                tone: "primary"
                enabled: root.runnerAvailable && !RealityCIController.busy
                         && RealityCIController.hasCampaign && !RealityCIController.terminal
                toolTip: root.runnerAvailable
                         ? "Run the campaign autonomously to promotion or rejection"
                         : "Control API is not connected"
                onClicked: RealityCIController.runCampaign()
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
                        title: "Campaign Control"
                        subtitle: RealityCIController.hasCampaign
                                  ? RealityCIController.campaignId
                                  : "No campaign"
                        iconSource: Theme.icon("project")
                        Layout.fillWidth: true
                    }

                    ScrollView {
                        id: controlScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        Column {
                            width: controlScroll.availableWidth

                            Section {
                                title: "Connection"
                                PropertyRow {
                                    label: "API URL"
                                    labelWidth: 90
                                    TextInput { id: serverField; text: RealityCIController.baseUrl; onEditingFinished: RealityCIController.setBaseUrl(text) }
                                }
                                PropertyRow {
                                    label: "Auth"
                                    labelWidth: 90
                                    TextInput {
                                        readOnly: true
                                        placeholderText: RealityCIController.tokenConfigured
                                                         ? "bearer token active (SERVO_API_TOKEN)"
                                                         : "no token required"
                                    }
                                }
                            }

                            Section {
                                title: "Campaign Setup"
                                PropertyRow {
                                    label: "Checkpoint"
                                    labelWidth: 90
                                    TextInput { id: campaignCheckpointField; text: "demo/occluded_pedestrian/baseline/baseline.pt" }
                                }
                                PropertyRow {
                                    label: "Train scen."
                                    labelWidth: 90
                                    TextInput { id: campaignScenariosField; text: "24" }
                                }
                                PropertyRow {
                                    label: "Hidden exam"
                                    labelWidth: 90
                                    TextInput { id: campaignExamField; text: "8" }
                                }
                                PropertyRow {
                                    label: "Protected"
                                    labelWidth: 90
                                    TextInput { id: campaignProtectedField; text: "4" }
                                }
                                PropertyRow {
                                    label: "Epochs"
                                    labelWidth: 90
                                    TextInput { id: campaignEpochsField; text: "10" }
                                }
                                PropertyRow {
                                    label: "Target"
                                    labelWidth: 90
                                    TextInput { id: campaignTargetField; text: "0.9" }
                                }
                                PropertyRow {
                                    label: "CI floor"
                                    labelWidth: 90
                                    TextInput { id: campaignFloorField; text: "0.5" }
                                }
                            }

                            Section {
                                title: "Workflow State"
                                PropertyRow {
                                    label: "State"
                                    labelWidth: 90
                                    TextInput { readOnly: true; text: RealityCIController.campaignState }
                                }
                                PropertyRow {
                                    label: "Terminal"
                                    labelWidth: 90
                                    TextInput { readOnly: true; text: RealityCIController.hasCampaign ? (RealityCIController.terminal ? "yes" : "no") : "-" }
                                }
                                PropertyRow {
                                    label: "Events"
                                    labelWidth: 90
                                    TextInput { readOnly: true; text: String(RealityCIController.eventCount) }
                                }
                            }

                            Text {
                                visible: RealityCIController.lastError.length > 0
                                text: RealityCIController.lastError
                                color: Theme.error
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                                wrapMode: Text.WrapAnywhere
                                width: parent.width - 24
                                leftPadding: 12
                            }
                        }
                    }
                }
            }

            Panel {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 560

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Agent Activity Timeline"
                        subtitle: RealityCIController.online
                                  ? RealityCIController.eventCount + " durable events"
                                  : "Offline - connect to load records"
                        iconSource: Theme.icon("table")
                        Layout.fillWidth: true
                    }

                    DataTable {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: RealityCIController
                        columns: [
                            { title: "SEQ", width: 56 },
                            { title: "EVENT", width: 210 },
                            { title: "DETAIL", width: 320 }
                        ]
                        emptyIcon: Theme.icon("run")
                        emptyTitle: RealityCIController.online ? "No campaign events" : "Control API offline"
                        emptyDescription: RealityCIController.online
                                          ? "Start the control API, create a campaign, and its durable event history appears here."
                                          : "Start the local control API (uvicorn cloud.control_api.app.main:app) or point the API URL at Cloud Run, then connect."
                        onRowActivated: function(row) {
                            root.selectedSequence =
                                RealityCIController.data(RealityCIController.index(row, 0), "sequence")
                        }
                    }
                }
            }

            Panel {
                SplitView.preferredWidth: 330
                SplitView.minimumWidth: 280
                SplitView.maximumWidth: 450

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Run Inspector"
                        subtitle: root.selectedSequence >= 0
                                  ? "event " + root.selectedSequence
                                  : "No selection"
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
                                PropertyRow {
                                    label: "Result"
                                    labelWidth: 90
                                    TextInput { readOnly: true; placeholderText: root.runCompletedPayload.result === undefined ? "Not evaluated" : String(root.runCompletedPayload.result) }
                                }
                                PropertyRow {
                                    label: "Scenario"
                                    labelWidth: 90
                                    TextInput { readOnly: true; placeholderText: root.runCompletedPayload.run_evidence_id === undefined ? "No selection" : String(root.runCompletedPayload.run_evidence_id) }
                                }
                                PropertyRow {
                                    label: "Policy"
                                    labelWidth: 90
                                    TextInput { readOnly: true; placeholderText: root.checkpointPayload.candidate_sha256 === undefined ? "No candidate yet" : String(root.checkpointPayload.parent_sha256) }
                                }
                            }

                            Section {
                                title: "Failure Evidence"
                                visible: Object.keys(root.failurePayload).length > 0
                                PropertyRow {
                                    label: "Class"
                                    labelWidth: 90
                                    TextInput { readOnly: true; placeholderText: String(root.failurePayload.failure_class) }
                                }
                                PropertyRow {
                                    label: "Severity"
                                    labelWidth: 90
                                    TextInput { readOnly: true; placeholderText: String(root.failurePayload.severity) }
                                }
                                PropertyRow {
                                    label: "Record"
                                    labelWidth: 90
                                    TextInput { readOnly: true; placeholderText: String(root.failurePayload.failure_id) }
                                }
                            }

                            Section {
                                title: "Selected Event Payload"
                                visible: root.selectedPayloadJson.length > 0
                                Rectangle {
                                    width: parent.width
                                    height: Math.min(260, payloadText.implicitHeight + 16)
                                    radius: Theme.cornerCard
                                    color: Theme.panelRaised

                                    TextEdit {
                                        id: payloadText
                                        anchors.fill: parent
                                        anchors.margins: 8
                                        readOnly: true
                                        text: root.prettyJson(root.selectedPayloadJson)
                                        color: Theme.textSecondary
                                        font.family: Theme.monoFont
                                        font.pixelSize: 9
                                        wrapMode: TextEdit.WrapAnywhere
                                        selectByMouse: true
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
