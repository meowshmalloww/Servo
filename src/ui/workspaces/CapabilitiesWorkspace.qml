import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../components"

Item {
    id: root

    readonly property bool acquisitionServiceAvailable: false
    property var debtSeries: []

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "Capabilities"
            subtitle: "Reality Debt, evidence coverage, and missing-reality acquisition requirements"
            iconSource: Theme.icon("capability")
            Layout.fillWidth: true

            TextButton { text: "Export Requirements"; iconSource: Theme.icon("export"); enabled: false }
            TextButton {
                text: "Create Capture Mission"
                iconSource: Theme.icon("plus")
                tone: "primary"
                enabled: false
                toolTip: root.acquisitionServiceAvailable
                         ? "Create an acquisition mission from selected gaps"
                         : "Acquisition service is not connected"
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
                        subtitle: Session.capabilityModel === null ? "No model" : "Connected"
                        iconSource: Theme.icon("capability")
                        Layout.fillWidth: true
                    }

                    SearchField {
                        Layout.fillWidth: true
                        Layout.leftMargin: 7
                        Layout.rightMargin: 7
                        Layout.topMargin: 7
                        Layout.bottomMargin: 6
                        hint: "Search capabilities"
                    }

                    DataTable {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: Session.capabilityModel
                        columns: [
                            { title: "CAPABILITY", width: 178 },
                            { title: "EVIDENCE", width: 94 },
                            { title: "DEBT", width: 82 }
                        ]
                        emptyIcon: Theme.icon("capability")
                        emptyTitle: "No capability model"
                        emptyDescription: "Import or define a capability taxonomy before Servo can aggregate evidence and calculate Reality Debt."
                    }
                }
            }

            SplitView {
                orientation: Qt.Vertical
                SplitView.fillWidth: true
                SplitView.minimumWidth: 680
                handle: SplitHandle { }

                LinePlot {
                    SplitView.preferredHeight: 280
                    SplitView.minimumHeight: 220
                    SplitView.maximumHeight: 390
                    title: "Reality Debt History"
                    unit: "selected capability"
                    values: root.debtSeries
                    minimum: 0
                    maximum: 1
                    lineColor: Theme.textSecondary
                }

                Panel {
                    SplitView.fillHeight: true
                    SplitView.minimumHeight: 260

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Evidence Coverage"
                            subtitle: "No capability selected"
                            iconSource: Theme.icon("table")
                            Layout.fillWidth: true
                        }

                        DataTable {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            model: null
                            columns: [
                                { title: "CONDITION", width: 220 },
                                { title: "REAL EVIDENCE", width: 120 },
                                { title: "SYNTHETIC EVIDENCE", width: 145 },
                                { title: "FRESHNESS", width: 110 },
                                { title: "GAP", width: 90 }
                            ]
                            emptyIcon: Theme.icon("capability")
                            emptyTitle: "No evidence records"
                            emptyDescription: "Coverage is populated from versioned runs, exams, and real-world acquisition records."
                        }
                    }
                }

                BottomDrawer {
                    SplitView.preferredHeight: implicitHeight
                    SplitView.minimumHeight: 34
                    SplitView.maximumHeight: 220
                    tabs: ["Debt Calculation", "Evidence Import", "Provenance"]
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
                                title: "Capability Gap"
                                PropertyRow { label: "Capability"; labelWidth: 112; TextInput { placeholderText: "No selection"; readOnly: true } }
                                PropertyRow { label: "Evidence state"; labelWidth: 112; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "Debt"; labelWidth: 112; TextInput { placeholderText: "Not calculated"; readOnly: true } }
                            }

                            Section {
                                title: "Missing Reality"
                                summary: "Acquisition requirement"
                                PropertyRow { label: "Environment"; labelWidth: 112; TextInput { placeholderText: "Unspecified" } }
                                PropertyRow { label: "Actors"; labelWidth: 112; TextInput { placeholderText: "Unspecified" } }
                                PropertyRow { label: "Behavior"; labelWidth: 112; TextInput { placeholderText: "Unspecified" } }
                                PropertyRow { label: "Sensor state"; labelWidth: 112; TextInput { placeholderText: "Unspecified" } }
                                PropertyRow { label: "Uncertainty"; labelWidth: 112; TextInput { placeholderText: "Unspecified" } }
                            }

                            Section {
                                title: "Capture Constraints"
                                PropertyRow { label: "Location"; labelWidth: 112; TextInput { placeholderText: "No location constraint" } }
                                PropertyRow { label: "Time / weather"; labelWidth: 112; TextInput { placeholderText: "No condition constraint" } }
                                PropertyRow { label: "Minimum samples"; labelWidth: 112; TextInput { placeholderText: "No sample target" } }
                                PropertyRow { label: "Acceptance"; labelWidth: 112; TextInput { placeholderText: "No evidence threshold" } }
                            }

                            Section {
                                title: "Provenance"
                                PropertyRow { label: "Derived from"; labelWidth: 112; TextInput { placeholderText: "No debt record"; readOnly: true } }
                                PropertyRow { label: "Policy version"; labelWidth: 112; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "Generated"; labelWidth: 112; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.borderSoft }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.margins: 8
                        spacing: 6
                        TextButton { text: "Save Requirement"; iconSource: Theme.icon("check"); enabled: false; Layout.fillWidth: true }
                        IconButton { iconSource: Theme.icon("export"); toolTip: "Export selected requirement"; enabled: false; buttonSize: Theme.controlHeight }
                    }
                }
            }
        }
    }
}
