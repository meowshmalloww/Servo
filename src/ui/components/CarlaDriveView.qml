pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import QtMultimedia
import "."

Item {
    id: root

    property bool active: false
    property string viewMode: "native"
    property bool followRunPose: !SimulationController.terminal
    property real inspectedRouteProgress: 0.0
    readonly property bool worldView: root.viewMode === "world"
    readonly property real displayedWorldProgress:
        root.followRunPose ? SimulationController.routeCompletion
                           : root.inspectedRouteProgress
    readonly property string selectedReplay: SimulationController.nativeReplayVideoUrl
    readonly property bool showReplay: !root.worldView && SimulationController.terminal
                                       && root.selectedReplay.length > 0
    readonly property string liveFrame: SimulationController.nativeFrameUrl
    readonly property string viewTitle:
        root.worldView ? "PUBLISHED T5 WORLD" : "NATIVE CARLA"
    readonly property string viewProvenance:
        root.worldView
        ? "Interactive five-tile Gaussian world · CARLA evidence attached separately · NOT UNIFIED"
        : "Uncomposited CARLA/Unreal physics camera"
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

    function openWorldView() {
        root.viewMode = "world";
        if (SimulationController.terminal) {
            // A finished video has no exact replay clock connected to the
            // interactive renderer. Start from the first registered route
            // camera and let the reviewer inspect the complete real world.
            root.followRunPose = false;
            root.inspectedRouteProgress = 0.0;
        } else {
            root.followRunPose = true;
        }
    }

    function updatePlayback() {
        if (root.active && root.showReplay) {
            if (replayPlayer.source.toString() !== root.selectedReplay)
                replayPlayer.source = root.selectedReplay;
            replayPlayer.play();
        } else {
            replayPlayer.pause();
        }
    }

    onActiveChanged: Qt.callLater(root.updatePlayback)
    onShowReplayChanged: Qt.callLater(root.updatePlayback)
    onSelectedReplayChanged: {
        replayPlayer.stop();
        replayPlayer.source = root.selectedReplay;
        Qt.callLater(root.updatePlayback);
    }

    Connections {
        target: SimulationController
        function onSessionChanged() {
            if (!SimulationController.terminal) {
                root.viewMode = "native";
                root.followRunPose = true;
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "#080b0d"
        visible: !root.worldView
    }

    Image {
        anchors.fill: parent
        anchors.bottomMargin: 58
        source: root.liveFrame
        visible: !root.worldView && !root.showReplay
                 && source.toString().length > 0
        asynchronous: false
        cache: false
        fillMode: Image.PreserveAspectFit
    }

    VideoOutput {
        id: replayOutput
        anchors.fill: parent
        anchors.bottomMargin: 58
        visible: !root.worldView && root.showReplay
        fillMode: VideoOutput.PreserveAspectFit
    }

    MediaPlayer {
        id: replayPlayer
        source: ""
        videoOutput: replayOutput
        // Evidence is a finite physical run. Repeating it made a completed
        // vehicle look as though it drove through the route terminus and
        // started again. Hold the final frame instead of looping.
        loops: 1
        onSourceChanged: Qt.callLater(root.updatePlayback)
        onMediaStatusChanged: {
            if (root.active && root.showReplay
                    && (mediaStatus === MediaPlayer.LoadedMedia
                        || mediaStatus === MediaPlayer.BufferedMedia))
                play();
        }
    }

    EmptyState {
        anchors.fill: parent
        anchors.bottomMargin: 58
        visible: !root.worldView && !root.showReplay
                 && root.liveFrame.length === 0
        iconSource: Theme.icon("run")
        title: SimulationController.busy ? "Starting physical CARLA run"
                                         : "No " + root.viewTitle.toLowerCase() + " frame"
        description: "Servo has not received an uncomposited CARLA/Unreal camera frame for this session."
    }

    Rectangle {
        z: 4
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 12
        width: viewSelector.implicitWidth + 16
        height: 38
        radius: 7
        color: Theme.overlayHud
        border.width: 1
        border.color: Theme.border
        visible: SimulationController.hasSession

        RowLayout {
            id: viewSelector
            anchors.centerIn: parent
            spacing: 5

            TextButton {
                compact: true
                text: "Native CARLA"
                selected: root.viewMode === "native"
                onClicked: root.viewMode = "native"
            }
            TextButton {
                compact: true
                text: "Actual T5 world"
                selected: root.worldView
                tone: root.worldView ? "primary" : "default"
                toolTip: "Open the actual interactive five-tile Gaussian world. The rejected composite is not shown."
                onClicked: root.openWorldView()
            }
        }
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
                          : "info"
                }
                StatusBadge {
                    text: root.worldView ? "VISUAL WORLD" : "NATIVE"
                    tone: root.worldView ? "warning" : "success"
                }
                Text {
                    text: root.worldView
                          ? root.viewTitle + " · CARLA RUN ATTACHED"
                          : (SimulationController.terminal ? "RECORDED " : "LIVE ")
                            + root.viewTitle
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
        // These frames were rendered from the rejected off-corridor Gaussian
        // sensor poses. Keep the sealed files for forensics, but never present
        // them as valid submission imagery.
        visible: false

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
        z: 4
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 70
        width: Math.min(parent.width - 40, provenanceLabel.implicitWidth + 24)
        height: 34
        radius: 7
        color: Theme.overlayHud
        border.width: 1
        border.color: root.worldView ? Theme.warning : Theme.border

        Text {
            id: provenanceLabel
            anchors.centerIn: parent
            text: root.viewProvenance
            color: root.worldView ? Theme.warning : Theme.textSecondary
            font.family: Theme.monoFont
            font.pixelSize: 9
            font.weight: Font.DemiBold
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
                visible: !root.worldView
                selected: Session.worldWeather === "clear"
                onClicked: root.newRunRequested("clear", 0.0)
            }
            TextButton {
                compact: true
                text: "Run snow"
                visible: !root.worldView
                selected: Session.worldWeather === "snow"
                tone: Session.worldWeather === "snow" ? "primary" : "default"
                onClicked: root.newRunRequested("snow", Session.worldSnowAccumulation)
            }
            Slider {
                visible: !root.worldView && Session.worldWeather === "snow"
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
                visible: !root.worldView && Session.worldWeather === "snow"
                text: Math.round(Session.worldSnowAccumulation * 100) + "%"
                color: Theme.textSecondary
                font.family: Theme.monoFont
                font.pixelSize: 9
            }
            TextButton {
                compact: true
                visible: root.worldView
                text: root.followRunPose ? "Following run" : "Inspect route"
                selected: root.followRunPose
                onClicked: root.followRunPose = !root.followRunPose
            }
            Slider {
                visible: root.worldView && !root.followRunPose
                Layout.preferredWidth: 170
                from: 0.0
                to: 1.0
                stepSize: 0.001
                value: root.inspectedRouteProgress
                onMoved: root.inspectedRouteProgress = value
                ToolTip.visible: hovered
                ToolTip.text: "Registered route " + Math.round(value * 100) + "%"
            }
            Text {
                visible: root.worldView
                text: Math.round(root.displayedWorldProgress * 100) + "% route"
                color: Theme.textSecondary
                font.family: Theme.monoFont
                font.pixelSize: 9
            }
            Text {
                Layout.fillWidth: true
                text: SimulationController.lastError.length > 0
                      ? SimulationController.lastError
                      : (SimulationController.terminal
                         ? (SimulationController.physicsGatePassed
                            ? "CARLA contact/gravity verified · collision geometry NOT VALIDATED"
                            : "CARLA physics gate did not pass or is not verified")
                         : "Authoritative synchronous CARLA · no unified T5/CARLA geometry claim")
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
