pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import QtMultimedia
import "."

Item {
    id: root

    property bool active: false
    readonly property bool hasReplay: SimulationController.replayVideoUrl.length > 0
    readonly property bool showReplay: root.hasReplay && SimulationController.terminal
    readonly property string liveFrame: SimulationController.integratedFrameUrl.length > 0
                                               ? SimulationController.integratedFrameUrl
                                               : SimulationController.policyFrameUrl
    readonly property string activeWeather:
        SimulationController.hasSession
        && SimulationController.scenarioWeather.length > 0
        ? SimulationController.scenarioWeather : Session.worldWeather
    readonly property real activeSnowAccumulation:
        SimulationController.hasSession
        && SimulationController.scenarioWeather.length > 0
        ? SimulationController.scenarioSnowAccumulation
        : Session.worldSnowAccumulation

    signal newRunRequested(string weather, real snowAccumulation)
    signal closeRequested()

    function updatePlayback() {
        if (root.active && root.showReplay)
            replayPlayer.play();
        else
            replayPlayer.pause();
    }

    onActiveChanged: Qt.callLater(root.updatePlayback)
    onShowReplayChanged: Qt.callLater(root.updatePlayback)

    Rectangle {
        anchors.fill: parent
        color: "#080b0d"
    }

    Image {
        anchors.fill: parent
        anchors.bottomMargin: 58
        source: root.liveFrame
        visible: !root.showReplay && source.toString().length > 0
        asynchronous: false
        cache: false
        fillMode: Image.PreserveAspectFit
    }

    VideoOutput {
        id: replayOutput
        anchors.fill: parent
        anchors.bottomMargin: 58
        visible: root.showReplay
        fillMode: VideoOutput.PreserveAspectFit
    }

    MediaPlayer {
        id: replayPlayer
        source: SimulationController.replayVideoUrl
        videoOutput: replayOutput
        // Evidence is a finite physical run. Repeating it made a completed
        // vehicle look as though it drove through the route terminus and
        // started again. Hold the final frame instead of looping.
        loops: 1
        onSourceChanged: Qt.callLater(root.updatePlayback)
    }

    EmptyState {
        anchors.fill: parent
        anchors.bottomMargin: 58
        visible: !root.showReplay && root.liveFrame.length === 0
        iconSource: Theme.icon("run")
        title: SimulationController.busy ? "Starting physical CARLA run"
                                         : "Waiting for CARLA evidence"
        description: "Servo is launching CARLA 0.9.16, applying authoritative vehicle controls, and compositing the Lincoln into the selected Gaussian road world."
    }

    Rectangle {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 12
        width: hud.implicitWidth + 22
        height: hud.implicitHeight + 18
        radius: 7
        color: Theme.overlayHud
        border.width: 1
        border.color: Theme.border

        ColumnLayout {
            id: hud
            anchors.centerIn: parent
            spacing: 5

            RowLayout {
                spacing: 7
                StatusBadge {
                    text: "CARLA 0.9.16"
                    tone: SimulationController.sessionState === "failed" ? "error"
                          : (SimulationController.terminal ? "success" : "info")
                }
                Text {
                    text: SimulationController.terminal ? "RECORDED PHYSICAL RUN" : "LIVE PHYSICS"
                    color: Theme.text
                    font.family: Theme.monoFont
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                }
            }

            Text {
                text: (SimulationController.speedMps * 3.6).toFixed(1) + " km/h  ·  "
                      + (SimulationController.routeCompletion * 100).toFixed(1) + "% route"
                color: Theme.text
                font.family: Theme.monoFont
                font.pixelSize: 13
                font.weight: Font.DemiBold
            }
            Text {
                text: SimulationController.policyName.length > 0
                      ? SimulationController.policyName
                      : "Waiting for policy identity"
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: 9
                elide: Text.ElideRight
            }
            Text {
                text: "Throttle " + SimulationController.throttle.toFixed(2)
                      + "  Brake " + SimulationController.brake.toFixed(2)
                      + "  Steer " + SimulationController.steering.toFixed(2)
                color: Theme.textSecondary
                font.family: Theme.monoFont
                font.pixelSize: 9
            }
            Text {
                text: "Collisions " + SimulationController.collisionCount
                      + "  ·  Lane events " + SimulationController.laneInvasionCount
                      + "  ·  Frame " + SimulationController.frameId
                color: SimulationController.collisionCount > 0 ? Theme.error : Theme.textMuted
                font.family: Theme.monoFont
                font.pixelSize: 9
            }
        }
    }

    Row {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: 12
        anchors.bottomMargin: 70
        spacing: 8
        visible: SimulationController.leftPolicyFrameUrl.length > 0
                 || SimulationController.rightPolicyFrameUrl.length > 0

        Repeater {
            model: [
                { "label": "FRONT LEFT", "source": SimulationController.leftPolicyFrameUrl },
                { "label": "FRONT RIGHT", "source": SimulationController.rightPolicyFrameUrl }
            ]

            delegate: Rectangle {
                required property var modelData
                width: 190
                height: 122
                radius: 7
                color: Theme.overlayHud
                border.width: 1
                border.color: Theme.border
                clip: true
                visible: modelData.source.length > 0

                Image {
                    anchors.fill: parent
                    anchors.margins: 1
                    source: modelData.source
                    asynchronous: false
                    cache: false
                    fillMode: Image.PreserveAspectCrop
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.margins: 6
                    width: cameraLabel.implicitWidth + 12
                    height: cameraLabel.implicitHeight + 6
                    radius: 4
                    color: Theme.overlayHud

                    Text {
                        id: cameraLabel
                        anchors.centerIn: parent
                        text: modelData.label
                        color: Theme.text
                        font.family: Theme.monoFont
                        font.pixelSize: 8
                        font.weight: Font.DemiBold
                    }
                }
            }
        }
    }

    Rectangle {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 12
        width: weatherLabel.implicitWidth + 22
        height: 34
        radius: 7
        color: Theme.overlayHud
        border.width: 1
        border.color: root.activeWeather === "snow" ? Theme.accent : Theme.border

        Text {
            id: weatherLabel
            anchors.centerIn: parent
            text: root.activeWeather === "snow"
                  ? "SNOW " + Math.round(root.activeSnowAccumulation * 100)
                    + "% · SURFACE DEPOSITION + LOW GRIP"
                  : "CLEAR · DRY GRIP"
            color: root.activeWeather === "snow" ? Theme.text : Theme.textSecondary
            font.family: Theme.monoFont
            font.pixelSize: 9
            font.weight: Font.DemiBold
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 58
        color: Theme.chrome
        border.width: 1
        border.color: Theme.border

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            spacing: 7

            TextButton {
                compact: true
                text: "Run clear"
                selected: Session.worldWeather === "clear"
                onClicked: root.newRunRequested("clear", 0.0)
            }
            TextButton {
                compact: true
                text: "Run snow"
                selected: Session.worldWeather === "snow"
                tone: Session.worldWeather === "snow" ? "primary" : "default"
                onClicked: root.newRunRequested("snow", Session.worldSnowAccumulation)
            }
            Slider {
                visible: Session.worldWeather === "snow"
                Layout.preferredWidth: 120
                from: 0.0
                to: 1.0
                stepSize: 0.05
                value: Session.worldSnowAccumulation
                onMoved: Session.worldSnowAccumulation = value
                ToolTip.visible: hovered
                ToolTip.text: "Inferred surface accumulation "
                              + Math.round(value * 100) + "%"
            }
            Text {
                visible: Session.worldWeather === "snow"
                text: Math.round(Session.worldSnowAccumulation * 100) + "%"
                color: Theme.textSecondary
                font.family: Theme.monoFont
                font.pixelSize: 9
            }
            Text {
                Layout.fillWidth: true
                text: SimulationController.lastError.length > 0
                      ? SimulationController.lastError
                      : (SimulationController.terminal
                         ? "Evidence replay from the completed CARLA physics session"
                         : "Authoritative synchronous CARLA · not the local demo car")
                color: SimulationController.lastError.length > 0 ? Theme.error : Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 9
                elide: Text.ElideRight
            }
            TextButton {
                compact: true
                text: "Pause"
                visible: !SimulationController.terminal
                enabled: SimulationController.sessionState === "running"
                onClicked: SimulationController.pauseSimulation()
            }
            TextButton {
                compact: true
                text: "Resume"
                visible: !SimulationController.terminal
                enabled: SimulationController.sessionState === "paused"
                onClicked: SimulationController.resumeSimulation()
            }
            TextButton {
                compact: true
                text: "Stop"
                tone: "danger"
                visible: !SimulationController.terminal
                enabled: SimulationController.hasSession
                onClicked: SimulationController.stopSimulation()
            }
            TextButton {
                compact: true
                text: "Close"
                onClicked: root.closeRequested()
            }
        }
    }
}
