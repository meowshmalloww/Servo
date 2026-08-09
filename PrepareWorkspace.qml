import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

Item {
    id: root

    property string selectedFile: "CrossingAdult"
    property string buildState: "idle"

    Timer {
        id: buildTimer
        interval: 1600
        onTriggered: root.buildState = "ready"
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 42
            color: Theme.panelRaised
            border.width: 1
            border.color: Theme.border

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 8

                Text {
                    text: "STUDY"
                    color: Theme.textMuted
                    font.family: Theme.uiFont
                    font.pixelSize: 9
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "Urban Occlusion"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }

                Text { text: "›"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 12 }
                Text { text: "Configuration"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 12 }

                Item { Layout.fillWidth: true }

                StatusDot {
                    dotColor: root.buildState === "ready" ? Theme.green
                                                            : (root.buildState === "building" ? Theme.accent : Theme.yellow)
                    pulse: root.buildState === "building"
                }

                Text {
                    text: root.buildState === "ready" ? "World ready"
                                                       : (root.buildState === "building" ? "Building world…" : "1 readiness issue")
                    color: Theme.textSecondary
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                }

                AppButton {
                    text: root.buildState === "building" ? "Building…" : (root.buildState === "ready" ? "Rebuild world" : "Build world")
                    glyph: root.buildState === "ready" ? "↻" : "▶"
                    tone: "primary"
                    enabled: root.buildState !== "building"
                    onClicked: {
                        root.buildState = "building"
                        buildTimer.restart()
                    }
                }
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: PaneDivider { }

            PanelFrame {
                SplitView.preferredWidth: 248
                SplitView.minimumWidth: 190
                SplitView.maximumWidth: 360

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Study files"
                        actionGlyph: "+"
                        actionToolTip: "Add input"
                        Layout.fillWidth: true
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: 7
                        Layout.rightMargin: 7
                        Layout.topMargin: 7
                        Layout.bottomMargin: 4
                        spacing: 5

                        ServoSearchField { Layout.fillWidth: true; hint: "Filter study files…" }
                        IconButton { glyph: "▽"; toolTip: "Filter"; buttonSize: 30 }
                    }

                    ScrollView {
                        id: studyFilesScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        Column {
                            width: studyFilesScroll.availableWidth
                            spacing: 0

                            TreeRow { label: "Policy"; glyph: "□"; expandable: true; expanded: true }
                            TreeRow { label: "CrossingAdult"; glyph: "P"; depth: 1; selected: root.selectedFile === label; suffix: "1.3.0"; onActivated: root.selectedFile = label }
                            TreeRow { label: "Evaluation adapter"; glyph: "↔"; depth: 1; suffix: "ready"; onActivated: root.selectedFile = label }

                            TreeRow { label: "Platform"; glyph: "◇"; expandable: true; expanded: true }
                            TreeRow { label: "EgoVehicle_V1"; glyph: "V"; depth: 1; suffix: "2.1.0"; selected: root.selectedFile === label; onActivated: root.selectedFile = label }

                            TreeRow { label: "Sensor rig"; glyph: "⌖"; expandable: true; expanded: true }
                            TreeRow { label: "EgoRig_V1"; glyph: "S"; depth: 1; suffix: "6 sensors"; selected: root.selectedFile === label; onActivated: root.selectedFile = label }
                            TreeRow { label: "SideRight calibration"; glyph: "!"; depth: 2; status: "warn"; statusColor: Theme.accent; selected: root.selectedFile === label; onActivated: root.selectedFile = label }

                            TreeRow { label: "Recordings"; glyph: "▦"; expandable: true; expanded: true; suffix: "2" }
                            TreeRow { label: "UrbanDrive_001"; glyph: "▣"; depth: 1; suffix: "18:42"; selected: root.selectedFile === label; onActivated: root.selectedFile = label }
                            TreeRow { label: "UrbanDrive_002"; glyph: "▣"; depth: 1; suffix: "11:18"; selected: root.selectedFile === label; onActivated: root.selectedFile = label }

                            TreeRow { label: "World"; glyph: "◫"; expandable: true; expanded: true }
                            TreeRow { label: "Paris_01"; glyph: "W"; depth: 1; suffix: "1.0.0"; selected: root.selectedFile === label; onActivated: root.selectedFile = label }

                            TreeRow { label: "Test plan"; glyph: "✓"; expandable: true; expanded: true }
                            TreeRow { label: "Occlusion_Suite"; glyph: "T"; depth: 1; suffix: "48 cases"; selected: root.selectedFile === label; onActivated: root.selectedFile = label }
                        }
                    }
                }
            }

            SplitView {
                orientation: Qt.Vertical
                SplitView.fillWidth: true
                SplitView.minimumWidth: 420
                SplitView.preferredWidth: 720
                handle: PaneDivider { }

                PanelFrame {
                    SplitView.fillHeight: true
                    SplitView.minimumHeight: 300

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Study configuration"
                            subtitle: "urban-occlusion.servo"
                            actionGlyph: "⋮"
                            actionToolTip: "Configuration actions"
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

                                ConfigSection {
                                    title: "Policy adapter"
                                    summary: "evaluation + training"

                                    PropertyRow {
                                        label: "Policy"
                                        UiComboBox { model: ["CrossingAdult (1.3.0)", "UrbanDriver (2.0.4)"] }
                                    }
                                    PropertyRow {
                                        label: "Inference adapter"
                                        UiComboBox { model: ["Default adapter", "ONNX Runtime", "TensorRT"] }
                                    }
                                    PropertyRow {
                                        label: "Training interface"
                                        UiComboBox { model: ["LoRA adapter · supported", "Evaluation only"] }
                                    }
                                }

                                ConfigSection {
                                    title: "Vehicle"
                                    summary: "EgoVehicle_V1"

                                    PropertyRow {
                                        label: "Platform"
                                        UiComboBox { model: ["EgoVehicle_V1 (2.1.0)", "DeliveryVan_V2 (1.4.2)"] }
                                    }
                                    PropertyRow {
                                        label: "Controller"
                                        UiComboBox { model: ["Ackermann deterministic", "CARLA adapter"] }
                                    }
                                    PropertyRow {
                                        label: "Initial state"
                                        UiTextField { text: "/config/vehicle/initial_state.json" }
                                    }
                                }

                                ConfigSection {
                                    title: "Sensors"
                                    summary: "6 configured"

                                    PropertyRow {
                                        label: "Sensor rig"
                                        UiComboBox { model: ["EgoRig_V1 (1.0.2)", "EgoRig_Minimal (1.1.0)"] }
                                    }
                                    PropertyRow {
                                        label: "Calibration"
                                        UiTextField { text: "/calibration/egorig_v1.calib" }
                                    }
                                    PropertyRow {
                                        label: "Render path"
                                        UiComboBox { model: ["Gaussian appearance + geometry", "Geometry only"] }
                                    }
                                }

                                ConfigSection {
                                    title: "Recording source"
                                    summary: "30 min 00 s"

                                    PropertyRow {
                                        label: "Recordings"
                                        UiComboBox { model: ["UrbanDrive_001 + UrbanDrive_002", "UrbanDrive_001"] }
                                    }
                                    PropertyRow {
                                        label: "Time range"
                                        UiTextField { text: "00:00:00.000 — 00:30:00.000" }
                                    }
                                    PropertyRow {
                                        label: "Synchronization"
                                        UiComboBox { model: ["Time sync · interpolate", "Frame lock"] }
                                    }
                                }

                                ConfigSection {
                                    title: "World compiler"
                                    summary: "hybrid deterministic"

                                    PropertyRow {
                                        label: "World source"
                                        UiComboBox { model: ["Paris_01 (1.0.0)", "Downtown_Block_01 (2.3.1)"] }
                                    }
                                    PropertyRow {
                                        label: "Compiler preset"
                                        UiComboBox { model: ["Validation · balanced", "Preview · fast", "Exam · strict"] }
                                    }
                                    PropertyRow {
                                        label: "Output"
                                        UiTextField { text: "/build/world/urban-occlusion" }
                                    }
                                }
                            }
                        }
                    }
                }

                PanelFrame {
                    SplitView.preferredHeight: 154
                    SplitView.minimumHeight: 100
                    SplitView.maximumHeight: 260

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 32
                            color: Theme.chrome
                            border.width: 1
                            border.color: Theme.border

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                spacing: 18

                                Text { text: "Problems  1"; color: Theme.accentBright; font.family: Theme.uiFont; font.pixelSize: 11; font.weight: Font.DemiBold }
                                Text { text: "Output"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 11 }
                                Text { text: "Files"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 11 }
                                Item { Layout.fillWidth: true }
                                IconButton { glyph: "×"; toolTip: "Collapse drawer"; buttonSize: 24 }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 44
                            Layout.leftMargin: 12
                            Layout.rightMargin: 12
                            spacing: 10

                            Text { text: "▲"; color: Theme.accent; font.family: Theme.uiFont; font.pixelSize: 11 }
                            ColumnLayout {
                                spacing: 1
                                Layout.fillWidth: true
                                Text { text: "Camera calibration missing"; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 11; font.weight: Font.DemiBold }
                                Text { text: "Sensor rig / SideRight · required before strict exam builds"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 10 }
                            }
                            AppButton { text: "Open calibration"; compact: true }
                        }

                        Item { Layout.fillHeight: true }
                    }
                }
            }

            PanelFrame {
                SplitView.preferredWidth: 286
                SplitView.minimumWidth: 238
                SplitView.maximumWidth: 380

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Readiness"
                        subtitle: root.buildState === "ready" ? "6 / 6" : "5 / 6"
                        actionGlyph: "↻"
                        actionToolTip: "Run checks"
                        Layout.fillWidth: true
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.margins: 12
                        spacing: 14

                        Repeater {
                            model: [
                                { name: "Policy adapter", detail: "Inference and training supported", ok: true },
                                { name: "Vehicle", detail: "Dynamics profile resolved", ok: true },
                                { name: "Sensors", detail: "6 sources discovered", ok: true },
                                { name: "Recording source", detail: "30:00 synchronized", ok: true },
                                { name: "World geometry", detail: "Collision mesh available", ok: true },
                                { name: "SideRight calibration", detail: root.buildState === "ready" ? "Generated for prototype" : "Calibration bundle missing", ok: root.buildState === "ready" }
                            ]

                            delegate: RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: 9

                                Text {
                                    text: modelData.ok ? "✓" : "▲"
                                    color: modelData.ok ? Theme.green : Theme.accentBright
                                    font.family: Theme.uiFont
                                    font.pixelSize: 13
                                    Layout.alignment: Qt.AlignTop
                                }

                                ColumnLayout {
                                    spacing: 2
                                    Layout.fillWidth: true

                                    Text { text: modelData.name; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 11; font.weight: Font.DemiBold }
                                    Text { text: modelData.detail; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 10; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                }
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.margins: 12
                        spacing: 7

                        Text { text: "BUILD OUTPUT"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; font.weight: Font.DemiBold }
                        PropertyRow { label: "World"; labelWidth: 78; Text { anchors.fill: parent; text: "urban-occlusion-v4"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                        PropertyRow { label: "Scenarios"; labelWidth: 78; Text { anchors.fill: parent; text: "48 validation · 12 hidden"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                        PropertyRow { label: "Estimate"; labelWidth: 78; Text { anchors.fill: parent; text: "4 min 18 s"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                    }

                    Item { Layout.fillHeight: true }
                }
            }
        }
    }
}
