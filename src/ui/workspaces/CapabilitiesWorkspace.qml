import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../components"

Item {
    id: root

    // Real availability: capability updates come from campaign debt records.
    readonly property bool acquisitionServiceAvailable: RealityCIController.online
    readonly property var debtPayload: RealityCIController.latestPayload("REALITY_DEBT_UPDATED")
    readonly property var capabilityPayload: RealityCIController.latestPayload("CAPABILITY_UPDATED")
    readonly property var weaknessPayload: RealityCIController.latestPayload("NEXT_WEAKNESS_SELECTED")
    readonly property var missionPayload: RealityCIController.latestPayload("CAPTURE_MISSION_CREATED")
    property var debtSeries: []
    property var eventRows: []

    function rebuildFromEvents() {
        const nextRows = []
        const updates = RealityCIController.payloadsOf("CAPABILITY_UPDATED")
        for (let i = 0; i < updates.length; ++i) {
            nextRows.push({
                capability: String(updates[i].capability),
                evidence: String(updates[i].state),
                checkpoint: String(updates[i].last_verified_checkpoint)
            })
        }
        root.eventRows = nextRows
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
            title: "Capabilities"
            subtitle: "Reality Debt, evidence coverage, and missing-reality acquisition requirements"
            helpText: "The capability register tracks every skill with its evidence state and Reality Debt score. Verified capabilities shrink the debt; blocked ones raise a capture mission instead of endless training."
            iconSource: Theme.icon("capability")
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

            StatusBadge {
                text: root.debtPayload.total_debt === undefined
                      ? "debt not computed"
                      : "reality debt " + Number(root.debtPayload.total_debt).toFixed(3)
                tone: root.debtPayload.total_debt === undefined ? "neutral" : "info"
                Layout.alignment: Qt.AlignVCenter
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: SplitHandle { }

            Panel {
                SplitView.preferredWidth: 360
                SplitView.minimumWidth: 300
                SplitView.maximumWidth: 500

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Capability Register"
                        subtitle: root.capabilityPayload.capability !== undefined
                                  ? String(root.capabilityPayload.capability) + " · " + String(root.capabilityPayload.state)
                                  : "No capability records"
                        iconSource: Theme.icon("capability")
                        Layout.fillWidth: true
                    }

                    RecordTable {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.topMargin: 6
                        rows: root.eventRows
                        columns: [
                            { title: "CAPABILITY", field: "capability", width: 210 },
                            { title: "EVIDENCE STATE", field: "evidence", width: 130 },
                            { title: "VERIFIED AT", field: "checkpoint", width: 150 }
                        ]
                        emptyIcon: Theme.icon("capability")
                        emptyTitle: "No capability model"
                        emptyDescription: "Capability states update only from durable promotion and exam records."
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
                    SplitView.minimumHeight: 220

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Next Weakness Selection"
                            subtitle: root.weaknessPayload.taxonomy_id !== undefined
                                      ? "autonomously selected"
                                      : "Awaiting a completed campaign"
                            iconSource: Theme.icon("search")
                            Layout.fillWidth: true
                        }

                        Section {
                            title: "Autonomous Continuation"
                            Layout.fillWidth: true
                            PropertyRow {
                                label: "Capability"
                                labelWidth: 112
                                TextInput { readOnly: true; placeholderText: String(root.weaknessPayload.taxonomy_id) }
                            }
                            PropertyRow {
                                label: "State"
                                labelWidth: 112
                                TextInput { readOnly: true; placeholderText: String(root.weaknessPayload.state) }
                            }
                        }

                        Section {
                            title: "Missing Reality"
                            summary: "Acquisition requirement"
                            visible: Object.keys(root.missionPayload).length > 0
                            PropertyRow {
                                label: "Mission"
                                labelWidth: 112
                                TextInput { readOnly: true; placeholderText: String(root.missionPayload.mission_id) }
                            }
                            PropertyRow {
                                label: "Capability"
                                labelWidth: 112
                                TextInput { readOnly: true; placeholderText: String(root.missionPayload.capability) }
                            }
                            Text {
                                width: parent.width - 24
                                leftPadding: 12
                                text: "No authorized world covers this capability, so the agent requested real-world capture evidence instead of training forever."
                                color: Theme.textMuted
                                font.family: Theme.uiFont
                                font.pixelSize: 9
                                wrapMode: Text.WrapAnywhere
                            }
                        }

                        Item { Layout.fillHeight: true }
                    }
                }

                Panel {
                    SplitView.preferredHeight: 240
                    SplitView.minimumHeight: 170
                    SplitView.maximumHeight: 360

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Debt Provenance"
                            subtitle: root.debtPayload.total_debt !== undefined
                                      ? "reproducible formula over evidence states"
                                      : "No debt record"
                            iconSource: Theme.icon("chart")
                            Layout.fillWidth: true
                        }

                        EmptyState {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            visible: root.debtPayload.total_debt === undefined
                            iconSource: Theme.icon("chart")
                            title: "Debt history not published yet"
                            description: "Reality Debt is computed by code from capability evidence; it appears here after a campaign commits a snapshot."
                        }

                        ColumnLayout {
                            visible: root.debtPayload.total_debt !== undefined
                            Layout.fillWidth: true
                            Layout.margins: 10
                            spacing: 4

                            StatusBadge {
                                text: "total reality debt " + Number(root.debtPayload.total_debt).toFixed(3)
                                tone: "info"
                            }
                            Text {
                                text: "Computed from capability severity, evidence state, coverage, confidence, and freshness - never from an LLM score."
                                color: Theme.textMuted
                                font.family: Theme.uiFont
                                font.pixelSize: 9
                                wrapMode: Text.WrapAnywhere
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }

            Panel {
                SplitView.preferredWidth: 370
                SplitView.minimumWidth: 320
                SplitView.maximumWidth: 500

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Acquisition Inspector"
                        subtitle: Object.keys(root.missionPayload).length > 0 ? "Capture mission active" : "No selection"
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
                                title: "Evidence Contract"
                                PropertyRow {
                                    label: "Derived from"
                                    labelWidth: 112
                                    TextInput { readOnly: true; placeholderText: root.debtPayload.total_debt === undefined ? "No debt record" : "campaign debt snapshot" }
                                }
                                PropertyRow {
                                    label: "Authority"
                                    labelWidth: 112
                                    TextInput { readOnly: true; placeholderText: "deterministic eligibility rules select weaknesses" }
                                }
                                PropertyRow {
                                    label: "Generated data"
                                    labelWidth: 112
                                    TextInput { readOnly: true; placeholderText: "excluded from collision and metric truth" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
