import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

Item {
    id: root

    property bool replaying: false
    property real playhead: 0.414
    property string decision: "pending"
    property string selectedCheckpoint: "v18"

    Timer {
        interval: 45
        repeat: true
        running: root.replaying
        onTriggered: {
            root.playhead += 0.0012
            if (root.playhead >= 1)
                root.playhead = 0
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
                anchors.leftMargin: 10
                anchors.rightMargin: 9
                spacing: 8

                Text { text: "RELEASE GATE"; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 12; font.weight: Font.DemiBold }
                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 20; color: Theme.borderStrong }
                Text { text: "candidate v18"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10 }
                Text { text: "vs"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 10 }
                Text { text: "baseline v14"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10 }

                Item { Layout.fillWidth: true }

                StatusDot { dotColor: root.decision === "rejected" ? Theme.red : Theme.green }
                Text {
                    text: root.decision === "promoted" ? "Promoted" : (root.decision === "rejected" ? "Rejected" : "All gates passed")
                    color: root.decision === "rejected" ? Theme.red : Theme.green
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                }
                AppButton { text: "Export evidence"; glyph: "↗" }
                IconButton { glyph: "⋮"; toolTip: "Verification actions" }
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: PaneDivider { }

            PanelFrame {
                SplitView.preferredWidth: 228
                SplitView.minimumWidth: 185
                SplitView.maximumWidth: 320

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0
                    PanelHeader { title: "Checkpoints"; subtitle: "5 retained"; actionGlyph: "▽"; actionToolTip: "Filter checkpoints"; Layout.fillWidth: true }

                    ServoSearchField { Layout.fillWidth: true; Layout.margins: 7; hint: "Search checkpoints…" }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1

                        Repeater {
                            model: [
                                { version: "v18", role: "Candidate", status: "candidate", tone: Theme.accent },
                                { version: "v17", role: "Ready", status: "passed", tone: Theme.green },
                                { version: "v16", role: "Ready", status: "passed", tone: Theme.green },
                                { version: "v15", role: "Ready", status: "passed", tone: Theme.green },
                                { version: "v14", role: "Baseline", status: "baseline", tone: Theme.textMuted }
                            ]

                            delegate: Rectangle {
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.preferredHeight: 43
                                Layout.leftMargin: 5
                                Layout.rightMargin: 5
                                radius: 2
                                color: root.selectedCheckpoint === modelData.version ? Theme.tint(Theme.accent, 0.22) : (checkpointArea.containsMouse ? Theme.surfaceHover : "transparent")
                                border.width: root.selectedCheckpoint === modelData.version ? 1 : 0
                                border.color: Theme.accent

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 9
                                    anchors.rightMargin: 9
                                    spacing: 8
                                    Text { text: modelData.status === "passed" ? "✓" : (modelData.status === "candidate" ? "◇" : "◆"); color: modelData.tone; font.family: Theme.uiFont; font.pixelSize: 11 }
                                    Text { text: modelData.version; color: Theme.text; font.family: Theme.monoFont; font.pixelSize: 11; font.weight: Font.DemiBold; Layout.preferredWidth: 40 }
                                    Text { text: modelData.role; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; Layout.fillWidth: true }
                                }

                                MouseArea { id: checkpointArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.selectedCheckpoint = modelData.version }
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border; Layout.topMargin: 8 }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.margins: 10
                        spacing: 6
                        Text { text: "COMPARISON"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; font.weight: Font.DemiBold }
                        PropertyRow { label: "Baseline"; labelWidth: 68; UiComboBox { model: ["v14", "v13", "v12"] } }
                        PropertyRow { label: "Candidate"; labelWidth: 68; UiComboBox { model: ["v18", "v17", "v16"] } }
                    }

                    Item { Layout.fillHeight: true }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 40
                        color: Theme.chrome
                        border.width: 1
                        border.color: Theme.border
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 9
                            anchors.rightMargin: 9
                            Text { text: "Hidden exam"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; Layout.fillWidth: true }
                            Text { text: "48 / 48"; color: Theme.green; font.family: Theme.monoFont; font.pixelSize: 10; font.weight: Font.DemiBold }
                        }
                    }
                }
            }

            SplitView {
                orientation: Qt.Vertical
                SplitView.fillWidth: true
                SplitView.minimumWidth: 440
                SplitView.preferredWidth: 760
                handle: PaneDivider { }

                PanelFrame {
                    SplitView.fillHeight: true
                    SplitView.minimumHeight: 280

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 34
                            Layout.minimumHeight: 34
                            Layout.maximumHeight: 34
                            spacing: 0

                            Rectangle {
                                color: Theme.chrome
                                border.width: 1
                                border.color: Theme.border
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 9
                                    anchors.rightMargin: 9
                                    Text { text: "Baseline v14"; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 11; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                    Text { text: "LOCKED"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9 }
                                }
                            }
                            Rectangle {
                                color: Theme.chrome
                                border.width: 1
                                border.color: Theme.border
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 9
                                    anchors.rightMargin: 9
                                    Text { text: "Candidate v18"; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 11; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                    Text { text: "LOCKED"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9 }
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumHeight: 180
                            spacing: 3

                            EngineViewport {
                                cameraName: "Baseline · Front"
                                trackedObjectName: "Pedestrian"
                                objectMetric: "detected 0.72 s late"
                                candidate: false
                                interactive: false
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                            }

                            EngineViewport {
                                cameraName: "Candidate · Front"
                                trackedObjectName: "Pedestrian"
                                objectMetric: "detected 1.18 s early"
                                candidate: true
                                interactive: false
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 39
                            color: Theme.chrome
                            border.width: 1
                            border.color: Theme.border

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                spacing: 5
                                IconButton { glyph: "|◀"; toolTip: "First frame" }
                                IconButton { glyph: "◀"; toolTip: "Step back" }
                                IconButton { glyph: root.replaying ? "Ⅱ" : "▶"; selected: root.replaying; onClicked: root.replaying = !root.replaying }
                                IconButton { glyph: "▶"; toolTip: "Step forward" }
                                Item { Layout.fillWidth: true }
                                Text { text: "00:12.43"; color: Theme.text; font.family: Theme.monoFont; font.pixelSize: 10 }
                                Rectangle { Layout.preferredWidth: 230; Layout.preferredHeight: 3; color: Theme.borderStrong; Rectangle { width: parent.width * root.playhead; height: parent.height; color: Theme.accent } }
                                Text { text: "Frame 374 / 1249"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9 }
                                AppButton { text: "1.0×"; compact: true }
                            }
                        }
                    }
                }

                PanelFrame {
                    SplitView.preferredHeight: 300
                    SplitView.minimumHeight: 220
                    SplitView.maximumHeight: 410

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0
                        PanelHeader { title: "Hidden exam · 48 scenarios"; subtitle: "no regressions"; actionGlyph: "↗"; actionToolTip: "Open report"; Layout.fillWidth: true }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 29
                            color: Theme.chrome
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                Text { text: "SUITE"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; Layout.fillWidth: true }
                                Text { text: "PASSED"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; Layout.preferredWidth: 74 }
                                Text { text: "FAILED"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; Layout.preferredWidth: 74 }
                                Text { text: "DELTA"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; Layout.preferredWidth: 70 }
                                Text { text: "STATUS"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; Layout.preferredWidth: 72 }
                            }
                        }

                        Repeater {
                            model: [
                                { suite: "Occlusion — Pedestrian", passed: "16", failed: "0", delta: "+12" },
                                { suite: "Occlusion — Cyclist", passed: "8", failed: "0", delta: "+6" },
                                { suite: "Occlusion — Vehicle", passed: "8", failed: "0", delta: "+8" },
                                { suite: "Crossing — Adult", passed: "6", failed: "0", delta: "+2" },
                                { suite: "Crossing — Child", passed: "5", failed: "0", delta: "±0" },
                                { suite: "Night — Occlusion", passed: "5", failed: "0", delta: "+1" }
                            ]

                            delegate: Rectangle {
                                required property int index
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.preferredHeight: 31
                                color: index % 2 === 0 ? Theme.tint(Theme.text, 0.018) : "transparent"
                                border.width: 1
                                border.color: Theme.border

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10
                                    Text { text: "›  " + modelData.suite; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; Layout.fillWidth: true }
                                    Text { text: modelData.passed; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 9; Layout.preferredWidth: 74 }
                                    Text { text: modelData.failed; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9; Layout.preferredWidth: 74 }
                                    Text { text: modelData.delta; color: modelData.delta === "±0" ? Theme.textMuted : Theme.green; font.family: Theme.monoFont; font.pixelSize: 9; Layout.preferredWidth: 70 }
                                    Text { text: "✓ PASS"; color: Theme.green; font.family: Theme.uiFont; font.pixelSize: 9; Layout.preferredWidth: 72 }
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 32
                            color: Theme.chrome
                            border.width: 1
                            border.color: Theme.borderStrong
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                Text { text: "Total"; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 10; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                Text { text: "48"; color: Theme.text; font.family: Theme.monoFont; font.pixelSize: 9; Layout.preferredWidth: 74 }
                                Text { text: "0"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9; Layout.preferredWidth: 74 }
                                Text { text: "+29"; color: Theme.green; font.family: Theme.monoFont; font.pixelSize: 9; Layout.preferredWidth: 70 }
                                Text { text: "✓ PASS"; color: Theme.green; font.family: Theme.uiFont; font.pixelSize: 9; Layout.preferredWidth: 72 }
                            }
                        }

                        Item { Layout.fillHeight: true }
                    }
                }
            }

            PanelFrame {
                SplitView.preferredWidth: 302
                SplitView.minimumWidth: 250
                SplitView.maximumWidth: 410

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0
                    PanelHeader { title: "Decision"; subtitle: root.decision === "pending" ? "ready" : root.decision; actionGlyph: "⋮"; Layout.fillWidth: true }

                    ScrollView {
                        id: decisionScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        Column {
                            width: decisionScroll.availableWidth

                            ConfigSection {
                                title: "Generalization"
                                summary: "91%"
                                PropertyRow { label: "Hidden exam"; labelWidth: 116; Text { anchors.fill: parent; text: "91%"; color: Theme.text; font.family: Theme.monoFont; font.pixelSize: 11; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignRight } }
                                PropertyRow { label: "Compared to v14"; labelWidth: 116; Text { anchors.fill: parent; text: "+27 pp"; color: Theme.green; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignRight } }
                            }

                            ConfigSection {
                                title: "Regression"
                                summary: "48 / 48 PASS"
                                PropertyRow { label: "Evaluated"; labelWidth: 116; Text { anchors.fill: parent; text: "48"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignRight } }
                                PropertyRow { label: "Passed"; labelWidth: 116; Text { anchors.fill: parent; text: "48"; color: Theme.green; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignRight } }
                                PropertyRow { label: "Failed"; labelWidth: 116; Text { anchors.fill: parent; text: "0"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignRight } }
                                PropertyRow { label: "Regressed"; labelWidth: 116; Text { anchors.fill: parent; text: "0"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignRight } }
                            }

                            ConfigSection {
                                title: "Reality Debt"
                                summary: "18.4% → 11.2%"
                                PropertyRow { label: "Baseline v14"; labelWidth: 116; Text { anchors.fill: parent; text: "18.4%"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignRight } }
                                PropertyRow { label: "Candidate v18"; labelWidth: 116; Text { anchors.fill: parent; text: "11.2%"; color: Theme.text; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignRight } }
                                PropertyRow { label: "Change"; labelWidth: 116; Text { anchors.fill: parent; text: "−7.2 pp"; color: Theme.green; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignRight } }
                            }

                            ConfigSection {
                                title: "Promotion policy"
                                summary: "satisfied"
                                ColumnLayout {
                                    width: parent.width
                                    spacing: 7
                                    Repeater {
                                        model: ["Hidden exam threshold met", "No prior capability regressed", "Reality Debt reduced", "Evidence package complete"]
                                        delegate: RowLayout {
                                            required property string modelData
                                            width: parent.width
                                            Layout.leftMargin: 10
                                            Layout.rightMargin: 10
                                            Text { text: "✓"; color: Theme.green; font.family: Theme.uiFont; font.pixelSize: 11 }
                                            Text { text: modelData; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; Layout.fillWidth: true }
                                        }
                                    }
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.leftMargin: 10
                                        Layout.rightMargin: 10
                                        Layout.bottomMargin: 8
                                        Layout.preferredHeight: 58
                                        color: Theme.field
                                        border.width: 1
                                        border.color: Theme.border
                                        Text { anchors.fill: parent; anchors.margins: 9; text: "No regressions detected. Candidate meets promotion policy."; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; wrapMode: Text.WordWrap; verticalAlignment: Text.AlignVCenter }
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 72
                        color: Theme.chrome
                        border.width: 1
                        border.color: Theme.border

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 8
                            AppButton {
                                text: root.decision === "promoted" ? "Promoted v18" : "Promote v18"
                                glyph: root.decision === "promoted" ? "✓" : "↑"
                                tone: "primary"
                                enabled: root.decision === "pending"
                                Layout.fillWidth: true
                                onClicked: root.decision = "promoted"
                            }
                            AppButton {
                                text: root.decision === "rejected" ? "Rejected" : "Reject"
                                tone: "danger"
                                enabled: root.decision === "pending"
                                Layout.fillWidth: true
                                onClicked: root.decision = "rejected"
                            }
                        }
                    }
                }
            }
        }
    }
}
