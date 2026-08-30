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
    property bool inspectorVisible: false
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
    readonly property var diagnosisPayload: RealityCIController.latestPayload("HYPOTHESES_PROPOSED")
    readonly property var rootCausePayload: RealityCIController.latestPayload("ROOT_CAUSE_ESTABLISHED")
    readonly property var curriculumPayload: RealityCIController.latestPayload("CURRICULUM_CREATED")
    readonly property var examPayload: RealityCIController.latestPayload("HIDDEN_EXAM_COMPLETED")
    readonly property var regressionPayload: RealityCIController.latestPayload("REGRESSION_COMPLETED")
    readonly property var promotedPayload: RealityCIController.latestPayload("CHECKPOINT_PROMOTED")
    readonly property var rejectedPayload: RealityCIController.latestPayload("CHECKPOINT_REJECTED")
    readonly property var debtPayload: RealityCIController.latestPayload("REALITY_DEBT_UPDATED")
    readonly property var nextPayload: RealityCIController.latestPayload("NEXT_WEAKNESS_SELECTED")
    readonly property var experimentPayloads: RealityCIController.payloadsOf("EXPERIMENT_COMPLETED")

    function hasEvent(type) {
        for (let row = 0; row < RealityCIController.eventCount; ++row) {
            if (RealityCIController.eventAt(row).event_type === type)
                return true
        }
        return false
    }

    function prettyJson(text) {
        if (text.length === 0)
            return ""
        try {
            return JSON.stringify(JSON.parse(text), null, 2)
        } catch (error) {
            return text
        }
    }

    function value(record, key, fallback) {
        if (record === undefined || record === null || record[key] === undefined)
            return fallback
        return String(record[key])
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
                text: "Details"
                iconSource: Theme.icon("inspector")
                compact: true
                selected: root.inspectorVisible
                toolTip: root.inspectorVisible ? "Hide run details" : "Show run details"
                onClicked: root.inspectorVisible = !root.inspectorVisible
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

            TextButton {
                text: "Cancel"
                iconSource: Theme.icon("close")
                compact: true
                tone: "danger"
                visible: RealityCIController.hasCampaign && !RealityCIController.terminal
                enabled: root.runnerAvailable && !RealityCIController.busy
                toolTip: "Durably cancel this campaign; repeated requests are idempotent"
                onClicked: RealityCIController.cancelCampaign("cancelled from campaign workspace")
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: SplitHandle { }

            Panel {
                SplitView.preferredWidth: 292
                SplitView.minimumWidth: 260
                SplitView.maximumWidth: 380

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
                                title: "Campaigns"
                                RowLayout {
                                    width: parent.width
                                    spacing: 6
                                    ComboBox {
                                        id: campaignPicker
                                        Layout.fillWidth: true
                                        model: RealityCIController.campaigns
                                        textRole: "campaign_id"
                                        valueRole: "campaign_id"
                                        displayText: RealityCIController.hasCampaign
                                                     ? RealityCIController.campaignId
                                                     : (currentText.length > 0 ? currentText : "Select campaign")
                                        onActivated: RealityCIController.selectCampaign(currentValue)
                                    }
                                    IconButton {
                                        iconSource: Theme.icon("refresh")
                                        toolTip: "Reload durable campaigns"
                                        onClicked: RealityCIController.listCampaigns()
                                    }
                                }
                            }

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
                                title: "Physical Simulation"
                                summary: SimulationController.hasSession
                                         ? SimulationController.sessionState : "No attached session"
                                PropertyRow {
                                    label: "Session"
                                    labelWidth: 90
                                    TextInput {
                                        id: simulationSessionField
                                        text: SimulationController.sessionId
                                        placeholderText: "sim-…"
                                    }
                                }
                                PropertyRow {
                                    label: "Result"
                                    labelWidth: 90
                                    TextInput {
                                        readOnly: true
                                        text: SimulationController.result.length > 0
                                              ? SimulationController.result : SimulationController.sessionState
                                    }
                                }
                                PropertyRow {
                                    label: "Failure"
                                    labelWidth: 90
                                    TextInput {
                                        readOnly: true
                                        text: SimulationController.failureClass
                                        placeholderText: "None"
                                    }
                                }
                                PropertyRow {
                                    label: "Evidence"
                                    labelWidth: 90
                                    TextInput {
                                        readOnly: true
                                        text: SimulationController.evidencePath
                                        placeholderText: SimulationController.hasSession
                                                         ? "Pending terminal evidence" : "Unavailable"
                                    }
                                }
                                PropertyRow {
                                    label: "Artifacts"
                                    labelWidth: 90
                                    TextInput {
                                        readOnly: true
                                        text: SimulationController.artifactPaths
                                        placeholderText: "Pending"
                                    }
                                }
                                Item {
                                    width: parent.width
                                    height: 42
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.margins: 8
                                        TextButton {
                                            Layout.fillWidth: true
                                            compact: true
                                            text: "Reattach"
                                            enabled: SimulationController.online
                                                     && simulationSessionField.text.length > 0
                                            onClicked: SimulationController.reattachSimulation(simulationSessionField.text)
                                        }
                                        TextButton {
                                            Layout.fillWidth: true
                                            compact: true
                                            text: "Stop"
                                            tone: "danger"
                                            enabled: SimulationController.hasSession && !SimulationController.terminal
                                            onClicked: SimulationController.stopSimulation()
                                        }
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
                SplitView.minimumWidth: 380

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

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 64
                        color: Theme.panelRaised
                        clip: true

                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: 1
                            color: Theme.borderSoft
                            opacity: 0.45
                        }

                        Flickable {
                            id: timelineFlick
                            anchors.fill: parent
                            anchors.margins: 6
                            contentWidth: timelineRow.implicitWidth + 6
                            contentHeight: height
                            flickableDirection: Flickable.HorizontalFlick
                            boundsBehavior: Flickable.StopAtBounds
                            clip: true
                            ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded; height: 4 }

                            Row {
                                id: timelineRow
                                height: parent.height
                                spacing: 7
                                Repeater {
                                    model: [
                                        { label: "Failure", event: "FAILURE_DETECTED" },
                                        { label: "Diagnosis", event: "HYPOTHESES_PROPOSED" },
                                        { label: "Experiments", event: "EXPERIMENT_COMPLETED" },
                                        { label: "Training", event: "CHECKPOINT_READY" },
                                        { label: "Verification", event: "HIDDEN_EXAM_COMPLETED" },
                                        { label: "Decision", event: root.hasEvent("CHECKPOINT_PROMOTED") ? "CHECKPOINT_PROMOTED" : "CHECKPOINT_REJECTED" },
                                        { label: "Reality Debt", event: "REALITY_DEBT_UPDATED" },
                                        { label: "Next", event: "NEXT_WEAKNESS_SELECTED" }
                                    ]
                                    delegate: Rectangle {
                                        required property var modelData
                                        width: 108
                                        height: 44
                                        radius: 8
                                        color: root.hasEvent(modelData.event) ? Theme.tintSuccess : Theme.panel
                                        border.width: 1
                                        border.color: root.hasEvent(modelData.event) ? Theme.success : Theme.borderSoft

                                        Column {
                                            anchors.centerIn: parent
                                            spacing: 2
                                            Text {
                                                anchors.horizontalCenter: parent.horizontalCenter
                                                text: modelData.label
                                                color: Theme.text
                                                font.family: Theme.uiFont
                                                font.pixelSize: 9
                                                font.weight: Font.DemiBold
                                            }
                                            Text {
                                                anchors.horizontalCenter: parent.horizontalCenter
                                                text: root.hasEvent(modelData.event) ? "COMPLETE" : "WAITING"
                                                color: root.hasEvent(modelData.event) ? Theme.success : Theme.textMuted
                                                font.family: Theme.monoFont
                                                font.pixelSize: 8
                                            }
                                        }
                                    }
                                }
                            }
                        }
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
                                          : "Start Servo with Start-Servo.ps1 to launch the local control API, then connect."
                        onRowActivated: function(row) {
                            root.selectedSequence =
                                RealityCIController.data(RealityCIController.index(row, 0), "sequence")
                        }
                    }
                }
            }

            Panel {
                visible: root.inspectorVisible
                SplitView.preferredWidth: 300
                SplitView.minimumWidth: 260
                SplitView.maximumWidth: 400

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
                                title: "Diagnosis"
                                visible: Object.keys(root.diagnosisPayload).length > 0
                                PropertyRow {
                                    label: "Method"
                                    labelWidth: 90
                                    TextInput { readOnly: true; text: root.value(root.diagnosisPayload, "diagnostician", "-") }
                                }
                                PropertyRow {
                                    label: "Summary"
                                    labelWidth: 90
                                    TextInput { readOnly: true; text: root.value(root.diagnosisPayload, "summary", "-") }
                                }
                                PropertyRow {
                                    label: "Root cause"
                                    labelWidth: 90
                                    TextInput { readOnly: true; text: root.value(root.rootCausePayload, "root_cause", "Not established") }
                                }
                            }

                            Section {
                                title: "Experiments"
                                visible: root.experimentPayloads.length > 0
                                PropertyRow {
                                    label: "Executed"
                                    labelWidth: 90
                                    TextInput { readOnly: true; text: String(root.experimentPayloads.length) }
                                }
                                PropertyRow {
                                    label: "Latest"
                                    labelWidth: 90
                                    TextInput {
                                        readOnly: true
                                        text: root.experimentPayloads.length > 0
                                              ? root.value(root.experimentPayloads[root.experimentPayloads.length - 1], "intervention", "-")
                                              : "-"
                                    }
                                }
                            }

                            Section {
                                title: "Training"
                                visible: Object.keys(root.curriculumPayload).length > 0
                                         || Object.keys(root.checkpointPayload).length > 0
                                PropertyRow {
                                    label: "Scenarios"
                                    labelWidth: 90
                                    TextInput { readOnly: true; text: root.value(root.curriculumPayload, "total_scenarios", "-") }
                                }
                                PropertyRow {
                                    label: "Checkpoint"
                                    labelWidth: 90
                                    TextInput { readOnly: true; text: root.value(root.checkpointPayload, "candidate_sha256", "Not ready") }
                                }
                                PropertyRow {
                                    label: "Val loss"
                                    labelWidth: 90
                                    TextInput { readOnly: true; text: root.value(root.checkpointPayload, "best_val_loss", "-") }
                                }
                            }

                            Section {
                                title: "Verification"
                                visible: Object.keys(root.examPayload).length > 0
                                         || Object.keys(root.regressionPayload).length > 0
                                PropertyRow {
                                    label: "Hidden exam"
                                    labelWidth: 90
                                    TextInput {
                                        readOnly: true
                                        text: root.value(root.examPayload, "baseline_success", "-")
                                              + " -> " + root.value(root.examPayload, "candidate_success", "-")
                                    }
                                }
                                PropertyRow {
                                    label: "Regression"
                                    labelWidth: 90
                                    TextInput { readOnly: true; text: root.value(root.regressionPayload, "max_drop_pp", "-") + " pp" }
                                }
                            }

                            Section {
                                title: "Decision"
                                visible: Object.keys(root.promotedPayload).length > 0
                                         || Object.keys(root.rejectedPayload).length > 0
                                PropertyRow {
                                    label: "Outcome"
                                    labelWidth: 90
                                    TextInput {
                                        readOnly: true
                                        text: Object.keys(root.promotedPayload).length > 0 ? "PROMOTED" : "REJECTED"
                                    }
                                }
                                PropertyRow {
                                    label: "Decision ID"
                                    labelWidth: 90
                                    TextInput {
                                        readOnly: true
                                        text: Object.keys(root.promotedPayload).length > 0
                                              ? root.value(root.promotedPayload, "decision_id", "-")
                                              : root.value(root.rejectedPayload, "decision_id", "-")
                                    }
                                }
                            }

                            Section {
                                title: "Reality Debt & Next Action"
                                visible: Object.keys(root.debtPayload).length > 0
                                         || Object.keys(root.nextPayload).length > 0
                                PropertyRow {
                                    label: "Debt"
                                    labelWidth: 90
                                    TextInput { readOnly: true; text: root.value(root.debtPayload, "total_debt", "-") }
                                }
                                PropertyRow {
                                    label: "Next"
                                    labelWidth: 90
                                    TextInput { readOnly: true; text: root.value(root.nextPayload, "taxonomy_id", "No eligible weakness") }
                                }
                            }

                            Section {
                                title: "Artifacts"
                                RowLayout {
                                    width: parent.width
                                    Text {
                                        Layout.fillWidth: true
                                        text: RealityCIController.artifacts.length + " files"
                                        color: Theme.textSecondary
                                        font.family: Theme.uiFont
                                        font.pixelSize: 10
                                    }
                                    TextButton {
                                        text: "Load"
                                        compact: true
                                        enabled: RealityCIController.hasCampaign
                                        onClicked: RealityCIController.fetchArtifacts()
                                    }
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
