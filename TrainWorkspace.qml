import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

Item {
    id: root

    property bool training: true
    property real progress: 0.58
    property string selectedJob: "run_031"

    Timer {
        interval: 700
        repeat: true
        running: root.training
        onTriggered: root.progress = Math.min(0.98, root.progress + 0.001)
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
                anchors.rightMargin: 9
                spacing: 6

                AppButton { text: root.training ? "Pause" : "Resume"; glyph: root.training ? "Ⅱ" : "▶"; onClicked: root.training = !root.training }
                AppButton { text: "Stop"; glyph: "■"; tone: "danger"; onClicked: root.training = false }
                AppButton { text: "Open artifacts"; glyph: "□" }

                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 20; color: Theme.borderStrong }

                Text { text: "CANDIDATE v18"; color: Theme.text; font.family: Theme.monoFont; font.pixelSize: 10; font.weight: Font.DemiBold }
                Text { text: "targeted occlusion adapter"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 11 }

                Item { Layout.fillWidth: true }

                Text { text: "Epoch  7 / 12"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10 }
                Rectangle {
                    Layout.preferredWidth: 180
                    Layout.preferredHeight: 4
                    color: Theme.borderStrong
                    Rectangle { width: parent.width * root.progress; height: parent.height; color: Theme.accent }
                }
                Text { text: "38 min remaining"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9 }
                IconButton { glyph: "⋮"; toolTip: "Training actions" }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 58
            color: Theme.chrome
            border.width: 1
            border.color: Theme.border

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 7

                Repeater {
                    model: [
                        { step: "1", name: "Failure analysis", state: "done" },
                        { step: "2", name: "Scenario generation", state: "done" },
                        { step: "3", name: "Trainer", state: "running" },
                        { step: "4", name: "Hidden exam", state: "pending" },
                        { step: "5", name: "Regression check", state: "pending" },
                        { step: "6", name: "Promote", state: "pending" }
                    ]

                    delegate: RowLayout {
                        required property int index
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 7

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 37
                            color: modelData.state === "running" ? Theme.tint(Theme.accent, 0.12) : Theme.surface
                            border.width: 1
                            border.color: modelData.state === "running" ? Theme.accent : Theme.border

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 9
                                anchors.rightMargin: 9
                                spacing: 7

                                Text { text: modelData.state === "done" ? "✓" : modelData.step; color: modelData.state === "done" ? Theme.green : (modelData.state === "running" ? Theme.accentBright : Theme.textMuted); font.family: Theme.monoFont; font.pixelSize: 10 }
                                Text { text: modelData.name; color: modelData.state === "pending" ? Theme.textMuted : Theme.text; font.family: Theme.uiFont; font.pixelSize: 10; elide: Text.ElideRight; Layout.fillWidth: true }
                                StatusDot { visible: modelData.state === "running"; dotColor: Theme.accent; pulse: true }
                            }
                        }

                        Text { visible: index < 5; text: "›"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 13 }
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
                SplitView.preferredWidth: 232
                SplitView.minimumWidth: 190
                SplitView.maximumWidth: 330

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Training jobs"
                        subtitle: "7 total"
                        actionGlyph: "+"
                        actionToolTip: "New training job"
                        Layout.fillWidth: true
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: 7
                        Layout.rightMargin: 7
                        Layout.topMargin: 7
                        Layout.bottomMargin: 4
                        spacing: 5
                        ServoSearchField { Layout.fillWidth: true; hint: "Search jobs…" }
                        IconButton { glyph: "▽"; toolTip: "Filter jobs"; buttonSize: 30 }
                    }

                    ScrollView {
                        id: jobsScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        Column {
                            width: jobsScroll.availableWidth
                            TreeRow { label: "Queued"; glyph: "○"; expandable: true; expanded: true; suffix: "2" }
                            TreeRow { label: "run_032"; glyph: "·"; depth: 1; suffix: "occlusion v3"; selected: root.selectedJob === label; onActivated: root.selectedJob = label }
                            TreeRow { label: "run_033"; glyph: "·"; depth: 1; suffix: "night v1"; selected: root.selectedJob === label; onActivated: root.selectedJob = label }

                            TreeRow { label: "Running"; glyph: "▶"; expandable: true; expanded: true; suffix: "1" }
                            TreeRow { label: "run_031"; glyph: "●"; depth: 1; suffix: "epoch 7"; status: "running"; statusColor: Theme.accent; selected: root.selectedJob === label; onActivated: root.selectedJob = label }

                            TreeRow { label: "Completed"; glyph: "✓"; expandable: true; expanded: true; suffix: "4" }
                            TreeRow { label: "run_030"; glyph: "✓"; depth: 1; suffix: "passed"; status: "ok"; statusColor: Theme.green; selected: root.selectedJob === label; onActivated: root.selectedJob = label }
                            TreeRow { label: "run_029"; glyph: "✓"; depth: 1; suffix: "passed"; status: "ok"; statusColor: Theme.green; selected: root.selectedJob === label; onActivated: root.selectedJob = label }
                            TreeRow { label: "run_028"; glyph: "✓"; depth: 1; suffix: "passed"; status: "ok"; statusColor: Theme.green; selected: root.selectedJob === label; onActivated: root.selectedJob = label }
                            TreeRow { label: "run_027"; glyph: "✓"; depth: 1; suffix: "passed"; status: "ok"; statusColor: Theme.green; selected: root.selectedJob === label; onActivated: root.selectedJob = label }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 36
                        color: Theme.chrome
                        border.width: 1
                        border.color: Theme.border
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 9
                            anchors.rightMargin: 9
                            Text { text: "Compute queue"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; Layout.fillWidth: true }
                            StatusDot { dotColor: Theme.green }
                            Text { text: "healthy"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9 }
                        }
                    }
                }
            }

            SplitView {
                orientation: Qt.Vertical
                SplitView.fillWidth: true
                SplitView.minimumWidth: 440
                SplitView.preferredWidth: 740
                handle: PaneDivider { }

                PanelFrame {
                    SplitView.preferredHeight: 245
                    SplitView.minimumHeight: 180
                    SplitView.maximumHeight: 360

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0
                        PanelHeader { title: "Training progress"; subtitle: "live · smoothed 0.6"; actionGlyph: "⋮"; actionToolTip: "Plot options"; Layout.fillWidth: true }
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            spacing: 3
                            MetricPlot {
                                title: "Training loss"
                                value: "0.0887"
                                lineColor: Theme.accent
                                minimum: 0
                                maximum: 1
                                values: [0.95, 0.72, 0.61, 0.48, 0.42, 0.32, 0.27, 0.20, 0.15, 0.13, 0.09, 0.088]
                                xStart: "epoch 0"
                                xEnd: "epoch 12"
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                            }
                            MetricPlot {
                                title: "Hidden-set score"
                                value: "0.8791"
                                lineColor: Theme.green
                                minimum: 0.5
                                maximum: 1
                                values: [0.61, 0.71, 0.76, 0.80, 0.82, 0.84, 0.85, 0.86, 0.87, 0.879]
                                xStart: "epoch 0"
                                xEnd: "epoch 12"
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                            }
                        }
                    }
                }

                PanelFrame {
                    SplitView.fillHeight: true
                    SplitView.minimumHeight: 200

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0
                        PanelHeader { title: "Training log"; subtitle: root.selectedJob; actionGlyph: "⌕"; actionToolTip: "Search log"; Layout.fillWidth: true }

                        Flickable {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            contentWidth: width
                            contentHeight: logText.implicitHeight + 20

                            Text {
                                id: logText
                                x: 12
                                y: 10
                                width: parent.width - 24
                                text: "[12:04:11] run_031: Starting adapter training 'urban_occ_v2'\n" +
                                      "[12:04:11] dataset: train=120,432  validation=15,054  hidden=15,054\n" +
                                      "[12:04:11] model parameters: 52,341,888  optimizer: AdamW\n" +
                                      "[12:04:11] mixed precision: fp16  accumulation: 4 steps\n" +
                                      "[12:07:42] epoch 1/12  loss=0.7421  hidden=0.6123  val=0.6589\n" +
                                      "[12:11:13] epoch 2/12  loss=0.4312  hidden=0.7018  val=0.7076\n" +
                                      "[12:14:44] epoch 3/12  loss=0.2857  hidden=0.7682  val=0.7639\n" +
                                      "[12:18:15] epoch 4/12  loss=0.1974  hidden=0.8126  val=0.8071\n" +
                                      "[12:21:46] epoch 5/12  loss=0.1453  hidden=0.8417  val=0.8330\n" +
                                      "[12:25:17] epoch 6/12  loss=0.1123  hidden=0.8631  val=0.8526\n" +
                                      "[12:28:48] epoch 7/12  loss=0.0887  hidden=0.8791  val=0.8687\n" +
                                      "[12:28:48] saved checkpoint: artifacts/candidate_v18.ckpt\n" +
                                      "[12:28:48] regression guard: no early-stop condition"
                                color: Theme.textSecondary
                                font.family: Theme.monoFont
                                font.pixelSize: 10
                                lineHeight: 1.42
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }
                }

                PanelFrame {
                    SplitView.preferredHeight: 145
                    SplitView.minimumHeight: 106
                    SplitView.maximumHeight: 220

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0
                        PanelHeader { title: "Artifacts"; subtitle: "2 files · 512.3 MB"; actionGlyph: "⋮"; Layout.fillWidth: true }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 27
                            color: Theme.chrome
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                Text { text: "NAME"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; Layout.fillWidth: true }
                                Text { text: "TYPE"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; Layout.preferredWidth: 100 }
                                Text { text: "SIZE"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; Layout.preferredWidth: 90 }
                                Text { text: "MODIFIED"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; Layout.preferredWidth: 130 }
                            }
                        }

                        Repeater {
                            model: [
                                { name: "candidate_v18.ckpt", type: "Checkpoint", size: "512.3 MB", modified: "12:28:48" },
                                { name: "metrics.json", type: "JSON", size: "48.7 KB", modified: "12:28:48" }
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
                                    Text { text: "□  " + modelData.name; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; Layout.fillWidth: true }
                                    Text { text: modelData.type; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; Layout.preferredWidth: 100 }
                                    Text { text: modelData.size; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9; Layout.preferredWidth: 90 }
                                    Text { text: modelData.modified; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9; Layout.preferredWidth: 130 }
                                }
                            }
                        }
                    }
                }
            }

            PanelFrame {
                SplitView.preferredWidth: 294
                SplitView.minimumWidth: 240
                SplitView.maximumWidth: 390

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0
                    PanelHeader { title: "Run configuration"; subtitle: "locked while running"; actionGlyph: "⋮"; Layout.fillWidth: true }

                    ScrollView {
                        id: runConfigScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        Column {
                            width: runConfigScroll.availableWidth
                            ConfigSection {
                                title: "Adapter"
                                PropertyRow { label: "Adapter name"; labelWidth: 104; Text { anchors.fill: parent; text: "urban_occ_v2"; color: Theme.text; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Base model"; labelWidth: 104; Text { anchors.fill: parent; text: "urbnet_v3"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Type"; labelWidth: 104; Text { anchors.fill: parent; text: "LoRA"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Rank / alpha"; labelWidth: 104; Text { anchors.fill: parent; text: "32 / 64"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                            }
                            ConfigSection {
                                title: "Dataset"
                                PropertyRow { label: "Recipe"; labelWidth: 104; Text { anchors.fill: parent; text: "urban_occ_v2"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Train split"; labelWidth: 104; Text { anchors.fill: parent; text: "120,432"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Validation"; labelWidth: 104; Text { anchors.fill: parent; text: "15,054"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Hidden set"; labelWidth: 104; Text { anchors.fill: parent; text: "15,054 · isolated"; color: Theme.green; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                            }
                            ConfigSection {
                                title: "Compute"
                                PropertyRow { label: "Device"; labelWidth: 104; Text { anchors.fill: parent; text: "NVIDIA RTX 4090"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Batch size"; labelWidth: 104; Text { anchors.fill: parent; text: "16 × 4 accumulation"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Precision"; labelWidth: 104; Text { anchors.fill: parent; text: "fp16 (AMP)"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                            }
                            ConfigSection {
                                title: "Regression guard"
                                PropertyRow { label: "Metric"; labelWidth: 104; Text { anchors.fill: parent; text: "hidden-set score"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Minimum gain"; labelWidth: 104; Text { anchors.fill: parent; text: "+0.001"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Patience"; labelWidth: 104; Text { anchors.fill: parent; text: "3 epochs"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Action"; labelWidth: 104; Text { anchors.fill: parent; text: "Stop and retain best"; color: Theme.accentBright; font.family: Theme.uiFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                            }
                        }
                    }
                }
            }
        }
    }
}
