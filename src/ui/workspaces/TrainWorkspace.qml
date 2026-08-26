import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../components"

Item {
    id: root

    // Real availability: training runs inside the connected campaign engine.
    readonly property bool trainerAvailable: RealityCIController.online
    readonly property var requestedPayload: RealityCIController.latestPayload("TRAINING_REQUESTED")
    readonly property var startedPayload: RealityCIController.latestPayload("TRAINING_STARTED")
    readonly property var checkpointPayload: RealityCIController.latestPayload("CHECKPOINT_READY")
    readonly property var curriculumPayload: RealityCIController.latestPayload("CURRICULUM_CREATED")
    readonly property var sealedPayload: RealityCIController.latestPayload("HIDDEN_SEEDS_SEALED")
    readonly property bool weightsDiffer: root.checkpointPayload.candidate_sha256 !== undefined
                                          && String(root.checkpointPayload.candidate_sha256)
                                             !== String(root.checkpointPayload.parent_sha256)

    property var stageRows: []

    function rebuildFromEvents() {
        const stages = root.curriculumPayload.stages === undefined
                       ? [] : root.curriculumPayload.stages
        const nextStageRows = []
        for (let i = 0; i < stages.length; ++i)
            nextStageRows.push({ stage: String(stages[i]) })
        root.stageRows = nextStageRows
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
            title: "Train"
            subtitle: "Targeted experience, supported training adapters, artifacts, and durable checkpoints"
            helpText: "Review the curriculum generated for the established capability gap and launch a real PyTorch fine-tune on training seeds only. Hidden seeds were sealed before any training data existed."
            iconSource: Theme.icon("train")
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
                text: "Start Training"
                iconSource: Theme.icon("play")
                tone: "primary"
                enabled: root.trainerAvailable && !RealityCIController.busy
                         && RealityCIController.hasCampaign && !RealityCIController.terminal
                toolTip: root.trainerAvailable
                         ? "Advance the campaign into the training stage"
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
                SplitView.preferredWidth: 300
                SplitView.minimumWidth: 250
                SplitView.maximumWidth: 420

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Curriculum"
                        subtitle: root.curriculumPayload.curriculum_id !== undefined
                                  ? String(root.curriculumPayload.total_scenarios) + " scenarios reserved"
                                  : "Not created yet"
                        iconSource: Theme.icon("train")
                        Layout.fillWidth: true
                    }

                    RecordTable {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.topMargin: 6
                        rows: root.stageRows
                        columns: [
                            { title: "STAGE", field: "stage", width: 220 }
                        ]
                        emptyIcon: Theme.icon("train")
                        emptyTitle: "No curriculum"
                        emptyDescription: "Stages appear after the causal gate establishes a capability gap."
                    }

                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.borderSoft }

                    Section {
                        title: "Hidden Seed Isolation"
                        Layout.fillWidth: true
                        PropertyRow {
                            label: "Sealed"
                            labelWidth: 96
                            TextInput {
                                readOnly: true
                                placeholderText: root.sealedPayload.sealed_sha256 === undefined
                                                 ? "not sealed yet"
                                                 : String(root.sealedPayload.scenario_count) + " scenarios · " + String(root.sealedPayload.sealed_sha256)
                            }
                        }
                        Text {
                            width: parent.width - 24
                            leftPadding: 12
                            text: "Sealed before training existed; the Trainer never sees these seeds."
                            color: Theme.textMuted
                            font.family: Theme.uiFont
                            font.pixelSize: 9
                            wrapMode: Text.WrapAnywhere
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
                    SplitView.minimumHeight: 160

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Checkpoint Identity"
                            subtitle: root.checkpointPayload.candidate_sha256 !== undefined
                                      ? "candidate committed"
                                      : "No candidate yet"
                            iconSource: Theme.icon("verify")
                            Layout.fillWidth: true
                        }

                        ScrollView {
                            id: identityScroll
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            contentWidth: availableWidth
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                            Column {
                                width: identityScroll.availableWidth

                                Section {
                                    title: "Weights Changed By Training"
                                    PropertyRow {
                                        label: "Baseline"
                                        labelWidth: 100
                                        TextInput { readOnly: true; placeholderText: String(root.checkpointPayload.parent_sha256) }
                                    }
                                    PropertyRow {
                                        label: "Candidate"
                                        labelWidth: 100
                                        TextInput { readOnly: true; placeholderText: String(root.checkpointPayload.candidate_sha256) }
                                    }
                                }

                                Section {
                                    title: "Job Record"
                                    PropertyRow {
                                        label: "Trainer"
                                        labelWidth: 100
                                        TextInput { readOnly: true; placeholderText: root.requestedPayload.trainer === undefined ? "not started" : String(root.requestedPayload.trainer) }
                                    }
                                    PropertyRow {
                                        label: "Scenarios"
                                        labelWidth: 100
                                        TextInput { readOnly: true; placeholderText: root.startedPayload.scenarios === undefined ? "-" : String(root.startedPayload.scenarios) }
                                    }
                                    PropertyRow {
                                        label: "Best val loss"
                                        labelWidth: 100
                                        TextInput { readOnly: true; placeholderText: root.checkpointPayload.best_val_loss === undefined ? "-" : String(root.checkpointPayload.best_val_loss) }
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    Layout.leftMargin: 12
                                    Layout.rightMargin: 12
                                    spacing: 8
                                    StatusBadge {
                                        text: root.weightsDiffer ? "weights differ - hash changed" : "no candidate yet"
                                        tone: root.weightsDiffer ? "success" : "neutral"
                                    }
                                }
                            }
                        }
                    }
                }

                Panel {
                    SplitView.preferredHeight: 190
                    SplitView.minimumHeight: 150
                    SplitView.maximumHeight: 280

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Training Objective"
                            subtitle: root.checkpointPayload.best_val_loss !== undefined
                                      ? "final validation loss " + String(root.checkpointPayload.best_val_loss)
                                      : "Awaiting a real training record"
                            iconSource: Theme.icon("chart")
                            Layout.fillWidth: true
                        }

                        EmptyState {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            iconSource: Theme.icon("chart")
                            title: "Per-step curves not published by this engine"
                            description: "The campaign engine commits final metrics and checkpoint hashes as durable records; per-step curves will stream once the trainer exports them through the API."
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
                        subtitle: root.requestedPayload.trainer === undefined ? "Unconfigured" : "From durable records"
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
                                PropertyRow {
                                    label: "Base policy"
                                    labelWidth: 100
                                    TextInput { readOnly: true; placeholderText: RealityCIController.hasCampaign ? "campaign baseline checkpoint" : "No policy selected" }
                                }
                                PropertyRow {
                                    label: "Interface"
                                    labelWidth: 100
                                    TextInput { readOnly: true; placeholderText: root.requestedPayload.trainer === undefined ? "Published by adapter" : String(root.requestedPayload.trainer) }
                                }
                            }

                            Section {
                                title: "Experience Dataset"
                                PropertyRow {
                                    label: "Dataset"
                                    labelWidth: 100
                                    TextInput { readOnly: true; placeholderText: root.startedPayload.scenarios === undefined ? "No dataset selected" : String(root.startedPayload.scenarios) + " seeded scenarios" }
                                }
                                PropertyRow {
                                    label: "Provenance"
                                    labelWidth: 100
                                    TextInput { readOnly: true; placeholderText: "deterministic pools · oracle labels from scenario state" }
                                }
                            }

                            Section {
                                title: "Compute"
                                PropertyRow {
                                    label: "Executor"
                                    labelWidth: 100
                                    TextInput { readOnly: true; placeholderText: "campaign engine (Cloud Run job target)" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
