import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

Item {
    id: root

    property bool running: true
    property real playhead: 0.414
    property string selectedObject: "Pedestrian_03"
    property string selectedClass: "pedestrian"

    Timer {
        interval: 40
        repeat: true
        running: root.running
        onTriggered: {
            root.playhead += 0.0012
            if (root.playhead >= 1) {
                root.playhead = 0
                root.running = false
            }
        }
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
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                spacing: 6

                AppButton {
                    text: root.running ? "Running" : "Run"
                    glyph: root.running ? "Ⅱ" : "▶"
                    tone: root.running ? "default" : "primary"
                    onClicked: root.running = !root.running
                }
                AppButton { text: "Stop"; glyph: "■"; onClicked: { root.running = false; root.playhead = 0 } }
                AppButton { text: "Step"; glyph: "▶|"; onClicked: { root.running = false; root.playhead = Math.min(1, root.playhead + 1 / 1249) } }

                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 22; color: Theme.borderStrong }

                Text {
                    text: "RUN 0248"
                    color: Theme.text
                    font.family: Theme.monoFont
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "Urban — Day — Occlusion"
                    color: Theme.textSecondary
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                }

                Item { Layout.fillWidth: true }

                StatusDot { dotColor: root.running ? Theme.green : Theme.textMuted; pulse: root.running }
                Text { text: root.running ? "Deterministic simulation" : "Paused"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10 }

                AppButton { text: "Create variants"; glyph: "+"; onClicked: variantPopup.open() }
                IconButton { glyph: "⋮"; toolTip: "Run actions" }
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: PaneDivider { }

            PanelFrame {
                SplitView.preferredWidth: 252
                SplitView.minimumWidth: 194
                SplitView.maximumWidth: 360

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Outliner"
                        subtitle: "42 actors"
                        actionGlyph: "+"
                        actionToolTip: "Add actor"
                        Layout.fillWidth: true
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: 7
                        Layout.rightMargin: 7
                        Layout.topMargin: 7
                        Layout.bottomMargin: 4
                        spacing: 5

                        ServoSearchField { Layout.fillWidth: true; hint: "Search scene…" }
                        IconButton { glyph: "▽"; toolTip: "Filter scene"; buttonSize: 30 }
                    }

                    ScrollView {
                        id: sceneScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        Column {
                            width: sceneScroll.availableWidth

                            TreeRow { label: "Study"; glyph: "▤"; expandable: true; expanded: true }
                            TreeRow { label: "World"; glyph: "◫"; depth: 1; expandable: true; expanded: true }
                            TreeRow { label: "Map"; glyph: "⌗"; depth: 2; suffix: "Paris_01" }
                            TreeRow { label: "Lighting"; glyph: "☼"; depth: 2; suffix: "overcast" }
                            TreeRow { label: "Weather"; glyph: "≋"; depth: 2; suffix: "clear" }

                            TreeRow { label: "Ego vehicle"; glyph: "V"; depth: 1; expandable: true; expanded: true }
                            TreeRow { label: "Vehicle"; glyph: "◇"; depth: 2; selected: root.selectedObject === "EgoVehicle_V1"; onActivated: { root.selectedObject = "EgoVehicle_V1"; root.selectedClass = "vehicle" } }
                            TreeRow { label: "Controller"; glyph: "⌁"; depth: 2 }

                            TreeRow { label: "Sensor rig"; glyph: "⌖"; depth: 1; expandable: true; expanded: true }
                            TreeRow { label: "Cameras"; glyph: "▣"; depth: 2; suffix: "4" }
                            TreeRow { label: "LiDAR"; glyph: "⌁"; depth: 2; suffix: "1" }
                            TreeRow { label: "Radar"; glyph: "◉"; depth: 2; suffix: "1" }
                            TreeRow { label: "IMU"; glyph: "+"; depth: 2 }

                            TreeRow { label: "Actors"; glyph: "◇"; depth: 1; expandable: true; expanded: true }
                            TreeRow { label: "Vehicles"; glyph: "V"; depth: 2; expandable: true; expanded: false; suffix: "14" }
                            TreeRow { label: "Pedestrians"; glyph: "P"; depth: 2; expandable: true; expanded: true; suffix: "8" }
                            TreeRow { label: "Pedestrian_01"; glyph: "·"; depth: 3; selected: root.selectedObject === label; onActivated: { root.selectedObject = label; root.selectedClass = "pedestrian" } }
                            TreeRow { label: "Pedestrian_02"; glyph: "·"; depth: 3; selected: root.selectedObject === label; onActivated: { root.selectedObject = label; root.selectedClass = "pedestrian" } }
                            TreeRow { label: "Pedestrian_03"; glyph: "·"; depth: 3; selected: root.selectedObject === label; status: "critical"; statusColor: Theme.accent; onActivated: { root.selectedObject = label; root.selectedClass = "pedestrian" } }
                            TreeRow { label: "Pedestrian_04"; glyph: "·"; depth: 3; selected: root.selectedObject === label; onActivated: { root.selectedObject = label; root.selectedClass = "pedestrian" } }
                        }
                    }
                }
            }

            SplitView {
                orientation: Qt.Vertical
                SplitView.fillWidth: true
                SplitView.minimumWidth: 430
                SplitView.preferredWidth: 760
                handle: PaneDivider { }

                EngineViewport {
                    SplitView.fillHeight: true
                    SplitView.minimumHeight: 260
                    trackedObjectName: root.selectedObject
                    objectMetric: root.selectedClass === "pedestrian" ? "confidence 0.28" : "tracked"
                    cameraName: "Camera · Front"
                    onObjectSelected: {
                        root.selectedObject = "Pedestrian_03"
                        root.selectedClass = "pedestrian"
                    }
                }

                TimelinePanel {
                    SplitView.preferredHeight: 206
                    SplitView.minimumHeight: 146
                    SplitView.maximumHeight: 290
                    position: root.playhead
                    running: root.running
                    onSeekRequested: value => root.playhead = value
                    onRunningToggled: root.running = !root.running
                }

                PanelFrame {
                    SplitView.preferredHeight: 160
                    SplitView.minimumHeight: 118
                    SplitView.maximumHeight: 250

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Telemetry"
                            subtitle: "12.43 s"
                            actionGlyph: "⋮"
                            actionToolTip: "Metric settings"
                            Layout.fillWidth: true
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            spacing: 3

                            MetricPlot {
                                title: "Detection confidence"
                                value: "0.28"
                                lineColor: Theme.teal
                                values: [0.64, 0.65, 0.62, 0.57, 0.29, 0.14, 0.18, 0.22, 0.25]
                                xStart: "8 s"
                                xEnd: "18 s"
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                            }
                            MetricPlot {
                                title: "Brake command"
                                value: "−7.12"
                                unit: "m/s²"
                                lineColor: Theme.red
                                minimum: -16
                                maximum: 2
                                values: [1.4, 1.4, 1.3, 0.8, -1.2, -11.8, -12.4, -12.2]
                                xStart: "8 s"
                                xEnd: "18 s"
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                            }
                            MetricPlot {
                                title: "Speed"
                                value: "13.2"
                                unit: "m/s"
                                lineColor: Theme.textSecondary
                                minimum: 0
                                maximum: 20
                                values: [16.2, 15.8, 15.3, 14.4, 12.8, 10.5, 6.4, 2.1, 0.2]
                                xStart: "8 s"
                                xEnd: "18 s"
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                            }
                        }
                    }
                }
            }

            PanelFrame {
                SplitView.preferredWidth: 294
                SplitView.minimumWidth: 238
                SplitView.maximumWidth: 390

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Inspector"
                        subtitle: root.selectedObject
                        actionGlyph: "⋮"
                        actionToolTip: "Inspector actions"
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

                            ConfigSection {
                                title: "Identity"
                                PropertyRow { label: "ID"; labelWidth: 88; Text { anchors.fill: parent; text: root.selectedObject; color: Theme.text; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Class"; labelWidth: 88; Text { anchors.fill: parent; text: root.selectedClass; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 11; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Track"; labelWidth: 88; Text { anchors.fill: parent; text: "actor_00038"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                            }

                            ConfigSection {
                                title: "Transform"
                                PropertyRow { label: "Position (m)"; labelWidth: 88; UiTextField { text: "−2.135   1.382   0.000" } }
                                PropertyRow { label: "Rotation"; labelWidth: 88; UiTextField { text: "0.0   0.0   90.0" } }
                                PropertyRow { label: "Scale"; labelWidth: 88; UiTextField { text: "1.000   1.000   1.000" } }
                            }

                            ConfigSection {
                                title: "Behavior"
                                PropertyRow { label: "Model"; labelWidth: 88; UiComboBox { model: ["CrossingAdult", "WaitingAdult", "Cyclist"] } }
                                PropertyRow { label: "State"; labelWidth: 88; Text { anchors.fill: parent; text: "Crossing"; color: Theme.teal; font.family: Theme.uiFont; font.pixelSize: 11; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Speed"; labelWidth: 88; UiTextField { text: "1.25 m/s" } }
                                PropertyRow { label: "Start time"; labelWidth: 88; UiTextField { text: "11.80 s" } }
                            }

                            ConfigSection {
                                title: "Evaluation role"
                                PropertyRow { label: "Role"; labelWidth: 88; UiComboBox { model: ["Critical object", "Context actor", "Distractor"] } }
                                PropertyRow { label: "Importance"; labelWidth: 88; UiComboBox { model: ["High", "Medium", "Low"] } }
                                PropertyRow { label: "Criterion"; labelWidth: 88; Text { anchors.fill: parent; text: "Must detect before 12.0 s"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                            }
                        }
                    }
                }
            }
        }
    }

    Popup {
        id: variantPopup
        width: 360
        height: 230
        anchors.centerIn: Overlay.overlay
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        padding: 0
        background: Rectangle { color: Theme.panelRaised; border.width: 1; border.color: Theme.borderStrong }

        contentItem: ColumnLayout {
            spacing: 0
            PanelHeader { title: "Create counterfactual variants"; actionGlyph: "×"; Layout.fillWidth: true; onActionTriggered: variantPopup.close() }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 14
                spacing: 8
                PropertyRow { label: "Variants"; UiTextField { text: "300" } }
                PropertyRow { label: "Strategy"; UiComboBox { model: ["Occlusion sweep", "Actor placement", "Sensor noise"] } }
                Item { Layout.fillHeight: true }
                RowLayout {
                    Layout.fillWidth: true

                    Item { Layout.fillWidth: true }

                    AppButton {
                        text: "Cancel"
                        onClicked: variantPopup.close()
                    }

                    AppButton {
                        text: "Create"
                        tone: "primary"
                        onClicked: variantPopup.close()
                    }
                }
            }
        }
    }
}
