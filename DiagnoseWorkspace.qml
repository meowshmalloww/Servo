import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

Item {
    id: root

    property string selectedFailure: "Run 0247"
    property int selectedHypothesis: 4
    property bool replaying: false
    property real playhead: 0.414
    property bool experimentRunning: false

    Timer {
        interval: 45
        repeat: true
        running: root.replaying
        onTriggered: {
            root.playhead += 0.0014
            if (root.playhead >= 0.82)
                root.playhead = 0.26
        }
    }

    Timer {
        id: experimentTimer
        interval: 1400
        onTriggered: root.experimentRunning = false
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

                Text { text: "FAILURE INVESTIGATION"; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 12; font.weight: Font.DemiBold }
                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 20; color: Theme.borderStrong }
                Text { text: root.selectedFailure; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 10 }
                Text { text: "▲  Occluded pedestrian"; color: Theme.accentBright; font.family: Theme.uiFont; font.pixelSize: 11 }
                Text { text: "Detection 0.72 s late"; color: Theme.red; font.family: Theme.monoFont; font.pixelSize: 10 }

                Item { Layout.fillWidth: true }

                AppButton { text: "Compare"; glyph: "⇄" }
                AppButton { text: "Export report"; glyph: "↗" }
                IconButton { glyph: "☆"; toolTip: "Pin investigation" }
                IconButton { glyph: "⋮"; toolTip: "More actions" }
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: PaneDivider { }

            PanelFrame {
                SplitView.preferredWidth: 258
                SplitView.minimumWidth: 205
                SplitView.maximumWidth: 370

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Failures"
                        subtitle: "18 unresolved"
                        actionGlyph: "+"
                        actionToolTip: "Import run"
                        Layout.fillWidth: true
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: 7
                        Layout.rightMargin: 7
                        Layout.topMargin: 7
                        Layout.bottomMargin: 5
                        spacing: 5
                        ServoSearchField { Layout.fillWidth: true; hint: "Search failures…" }
                        IconButton { glyph: "▽"; toolTip: "Filter failures"; buttonSize: 30 }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 28
                        color: Theme.chrome
                        Text { anchors.left: parent.left; anchors.leftMargin: 10; anchors.verticalCenter: parent.verticalCenter; text: "TODAY"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; font.weight: Font.DemiBold }
                    }

                    ScrollView {
                        id: failuresScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        Column {
                            width: failuresScroll.availableWidth
                            spacing: 1

                            Repeater {
                                model: [
                                    { run: "Run 0247", time: "10:28:14", label: "Occluded pedestrian", state: "open", tone: Theme.red },
                                    { run: "Run 0246", time: "10:22:03", label: "Clear", state: "passed", tone: Theme.green },
                                    { run: "Run 0245", time: "10:15:42", label: "Clear", state: "passed", tone: Theme.green },
                                    { run: "Run 0244", time: "10:09:31", label: "Late braking", state: "open", tone: Theme.accent },
                                    { run: "Run 0243", time: "10:03:18", label: "Clear", state: "passed", tone: Theme.green },
                                    { run: "Run 0242", time: "09:57:05", label: "Map mismatch", state: "review", tone: Theme.yellow },
                                    { run: "Run 0241", time: "09:50:51", label: "Clear", state: "passed", tone: Theme.green },
                                    { run: "Run 0240", time: "09:44:37", label: "Clear", state: "passed", tone: Theme.green }
                                ]

                                delegate: Rectangle {
                                    required property var modelData
                                    width: parent.width
                                    height: 58
                                    color: root.selectedFailure === modelData.run ? Theme.tint(Theme.accent, 0.15) : (failureArea.containsMouse ? Theme.surfaceHover : "transparent")
                                    border.width: root.selectedFailure === modelData.run ? 1 : 0
                                    border.color: root.selectedFailure === modelData.run ? Theme.accent : "transparent"

                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 10
                                        anchors.rightMargin: 9
                                        anchors.topMargin: 7
                                        anchors.bottomMargin: 7
                                        spacing: 2

                                        RowLayout {
                                            Layout.fillWidth: true
                                            Text { text: modelData.run; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 11; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                            Text { text: modelData.state === "passed" ? "✓" : "▲"; color: modelData.tone; font.family: Theme.uiFont; font.pixelSize: 11 }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Text { text: modelData.time; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9 }
                                            Text { text: modelData.label; color: modelData.state === "passed" ? Theme.textMuted : Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; Layout.fillWidth: true; horizontalAlignment: Text.AlignRight }
                                        }
                                    }

                                    MouseArea {
                                        id: failureArea
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: root.selectedFailure = modelData.run
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 35
                        color: Theme.chrome
                        border.width: 1
                        border.color: Theme.border
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            Text { text: "All runs"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; Layout.fillWidth: true }
                            Text { text: "1,287"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 10 }
                        }
                    }
                }
            }

            SplitView {
                orientation: Qt.Vertical
                SplitView.fillWidth: true
                SplitView.minimumWidth: 440
                SplitView.preferredWidth: 700
                handle: PaneDivider { }

                EngineViewport {
                    SplitView.fillHeight: true
                    SplitView.minimumHeight: 250
                    cameraName: "Failure camera · Front"
                    trackedObjectName: "Pedestrian"
                    objectMetric: "detected +0.72 s late"
                    showTrajectory: true
                }

                TimelinePanel {
                    SplitView.preferredHeight: 180
                    SplitView.minimumHeight: 135
                    SplitView.maximumHeight: 260
                    position: root.playhead
                    running: root.replaying
                    onSeekRequested: value => root.playhead = value
                    onRunningToggled: root.replaying = !root.replaying
                }

                PanelFrame {
                    SplitView.preferredHeight: 225
                    SplitView.minimumHeight: 160
                    SplitView.maximumHeight: 330

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        PanelHeader {
                            title: "Counterfactual experiments"
                            subtitle: "4 completed"
                            actionGlyph: "⋮"
                            actionToolTip: "Experiment options"
                            Layout.fillWidth: true
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 29
                            color: Theme.chrome

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                spacing: 8
                                Text { text: "INTERVENTION"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                Text { text: "MEASURE"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; Layout.preferredWidth: 100 }
                                Text { text: "Δ"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; Layout.preferredWidth: 52 }
                                Text { text: "RESULT"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; Layout.preferredWidth: 92 }
                            }
                        }

                        Repeater {
                            model: [
                                { intervention: "Remove occluder (parked van)", measure: "Detection conf", delta: "+0.62", result: "Crash avoided" },
                                { intervention: "Perfect perception oracle", measure: "TTC", delta: "+1.85 s", result: "Crash avoided" },
                                { intervention: "Reveal pedestrian 0.3 s earlier", measure: "Brake time", delta: "+0.41 s", result: "Crash avoided" },
                                { intervention: "Increase detection range +20 m", measure: "Detection conf", delta: "+0.47", result: "Crash avoided" }
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
                                    spacing: 8
                                    Text { text: modelData.intervention; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; elide: Text.ElideRight; Layout.fillWidth: true }
                                    Text { text: modelData.measure; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; Layout.preferredWidth: 100 }
                                    Text { text: modelData.delta; color: Theme.teal; font.family: Theme.monoFont; font.pixelSize: 9; Layout.preferredWidth: 52 }
                                    Text { text: modelData.result; color: Theme.green; font.family: Theme.uiFont; font.pixelSize: 9; Layout.preferredWidth: 92 }
                                }
                            }
                        }

                        Item { Layout.fillHeight: true }
                    }
                }
            }

            PanelFrame {
                SplitView.preferredWidth: 336
                SplitView.minimumWidth: 275
                SplitView.maximumWidth: 460

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 35
                        color: Theme.chrome
                        border.width: 1
                        border.color: Theme.border

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 9
                            anchors.rightMargin: 9
                            spacing: 16
                            Text { text: "Evidence & analysis"; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 11; font.weight: Font.DemiBold }
                            Text { text: "Sensor data"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 10 }
                            Text { text: "Logs"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 10 }
                            Item { Layout.fillWidth: true }
                        }
                    }

                    ScrollView {
                        id: analysisScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        Column {
                            width: analysisScroll.availableWidth

                            ConfigSection {
                                title: "Overview"
                                PropertyRow { label: "Scenario"; labelWidth: 90; Text { anchors.fill: parent; text: "Urban_Intersection_Occlusion"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 9; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Weather"; labelWidth: 90; Text { anchors.fill: parent; text: "Clear · dry road · light traffic"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                                PropertyRow { label: "Outcome"; labelWidth: 90; Text { anchors.fill: parent; text: "●  Failure · Near miss"; color: Theme.red; font.family: Theme.uiFont; font.pixelSize: 10; verticalAlignment: Text.AlignVCenter } }
                            }

                            ConfigSection {
                                title: "Causal hypotheses"
                                summary: "5 tested"

                                Repeater {
                                    model: [
                                        { id: "H1", name: "Not detected", p: "p=0.03", status: "Rejected" },
                                        { id: "H2", name: "Detected late", p: "p=0.07", status: "Rejected" },
                                        { id: "H3", name: "Planner failed", p: "p=0.11", status: "Rejected" },
                                        { id: "H4", name: "Braking limit", p: "p=0.24", status: "Rejected" },
                                        { id: "H5", name: "Partial occlusion", p: "p=0.0003", status: "Supported" }
                                    ]

                                    delegate: Rectangle {
                                        required property int index
                                        required property var modelData
                                        width: parent.width
                                        height: 48
                                        color: root.selectedHypothesis === index ? Theme.tint(Theme.accent, 0.12) : (hypArea.containsMouse ? Theme.surfaceHover : "transparent")
                                        border.width: root.selectedHypothesis === index ? 1 : 0
                                        border.color: root.selectedHypothesis === index ? Theme.accent : "transparent"

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.leftMargin: 10
                                            anchors.rightMargin: 10
                                            spacing: 8
                                            Text { text: modelData.id; color: root.selectedHypothesis === index ? Theme.accentBright : Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 10 }
                                            ColumnLayout {
                                                spacing: 1
                                                Layout.fillWidth: true
                                                Text { text: modelData.name; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 11; font.weight: Font.DemiBold }
                                                Text { text: modelData.status; color: modelData.status === "Supported" ? Theme.green : Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9 }
                                            }
                                            Text { text: modelData.p; color: root.selectedHypothesis === index ? Theme.accentBright : Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9 }
                                        }

                                        MouseArea { id: hypArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.selectedHypothesis = index }
                                    }
                                }
                            }

                            ConfigSection {
                                title: "Causal finding"
                                summary: "91% confidence"

                                ColumnLayout {
                                    width: parent.width
                                    spacing: 8

                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.leftMargin: 10
                                        Layout.rightMargin: 10
                                        Layout.topMargin: 10
                                        Layout.preferredHeight: 102
                                        color: Theme.field
                                        border.width: 1
                                        border.color: Theme.accent

                                        ColumnLayout {
                                            anchors.fill: parent
                                            anchors.margins: 10
                                            spacing: 5
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Text { text: "Partial occlusion"; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 13; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                                Text { text: "91%"; color: Theme.teal; font.family: Theme.monoFont; font.pixelSize: 17; font.weight: Font.DemiBold }
                                            }
                                            Text { text: "The parked van delayed confident perception until the pedestrian had entered the crosswalk. Oracle perception avoids the event."; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                        }
                                    }

                                    Text { Layout.leftMargin: 10; text: "Oracle perception:  SAFE"; color: Theme.green; font.family: Theme.monoFont; font.pixelSize: 10; font.weight: Font.DemiBold }

                                    AppButton {
                                        Layout.leftMargin: 10
                                        Layout.rightMargin: 10
                                        Layout.fillWidth: true
                                        text: root.experimentRunning ? "Running ablation…" : "Run supporting ablation"
                                        glyph: "▶"
                                        tone: "primary"
                                        enabled: !root.experimentRunning
                                        onClicked: { root.experimentRunning = true; experimentTimer.restart() }
                                    }
                                }
                            }

                            ConfigSection {
                                title: "Next action"
                                summary: "agent proposal"
                                ColumnLayout {
                                    width: parent.width
                                    spacing: 8
                                    Text { Layout.leftMargin: 10; Layout.rightMargin: 10; Layout.fillWidth: true; text: "Generate targeted scenarios that vary parked-vehicle occlusion, pedestrian reveal time, and sensor confidence."; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; wrapMode: Text.WordWrap }
                                    AppButton { Layout.leftMargin: 10; Layout.rightMargin: 10; Layout.bottomMargin: 10; Layout.fillWidth: true; text: "Generate curriculum"; glyph: "+" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
