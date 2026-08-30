pragma ComponentBehavior: Bound

import QtCore
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../components"

Item {
    id: root

    readonly property var selectedWorld: WorldLibraryModel.selectedWorld
    readonly property bool hasSelection: WorldLibraryModel.hasSelection
    readonly property string selectedWorldId: root.selectedWorld
                                                ? String(root.selectedWorld.worldId || "") : ""
    readonly property url selectedPreviewUrl: {
        const value = root.selectedWorld
                      ? root.selectedWorld.previewUrl : undefined;
        return value === undefined || value === null ? "" : value;
    }
    readonly property string selectedPlyPath: root.selectedWorld
                                                 ? String(root.selectedWorld.plyPath || "")
                                                 : ""
    readonly property string selectedWorldPath: root.selectedWorld
                                                 ? String(root.selectedWorld.worldPath || "")
                                                 : ""
    readonly property var routeTiles: root.selectedWorld
                                      ? (root.selectedWorld.routeTiles || []) : []
    property int activeRouteTileIndex: 0
    property real pendingRouteFrame: -1
    property bool automaticRouteStreaming: true
    readonly property int routeFrameCount: root.routeTiles.length > 0
                                            ? Math.max(1, Number(root.routeTiles[
                                                root.routeTiles.length - 1].cameraEndExclusive || 1))
                                            : 1
    readonly property string explorePlyPath: root.routeTiles.length > 0
                                              ? String(root.routeTiles[Math.max(
                                                  0, Math.min(root.routeTiles.length - 1,
                                                              root.activeRouteTileIndex))].plyPath || "")
                                              : root.selectedPlyPath
    readonly property var recordedFrameUrls: root.selectedWorld
                                               ? (root.selectedWorld.recordedFrameUrls || [])
                                               : []
    readonly property int recordedFrameCount: root.recordedFrameUrls.length
    readonly property int recordedFrameIndex: root.recordedFrameCount > 1
                                              ? Math.max(0, Math.min(
                                                  root.recordedFrameCount - 1,
                                                  Math.round(root.recordedProgress
                                                             * (root.recordedFrameCount - 1))))
                                              : 0
    readonly property url recordedFrameUrl: root.recordedFrameCount > 0
                                             ? root.recordedFrameUrls[root.recordedFrameIndex]
                                             : ""
    readonly property bool selectedWorldPublished: root.hasSelection
                                                 && root.selectedWorld.published === true
    property string noticeText: ""
    property bool exploreMode: false
    property bool driveMode: false
    property bool carlaDriveMode: false
    property bool pendingDriveStart: false
    readonly property bool nativeDriveSmoke: Qt.application.arguments.indexOf(
                                                 "--native-drive-smoke") >= 0
    property bool detailsVisible: false
    property bool moveForward: false
    property bool moveBackward: false
    property bool moveLeft: false
    property bool moveRight: false
    property bool moveUp: false
    property bool moveDown: false
    property int visualizationMode: 0
    property real snowAccumulation: Session.worldWeather === "snow"
                                    ? Session.worldSnowAccumulation : 0.0
    Behavior on snowAccumulation {
        enabled: Theme.motionEnabled
        NumberAnimation { duration: 2800; easing.type: Easing.InOutCubic }
    }
    // Explore always means the reconstructed Gaussian world. Recorded frames
    // are an explicit reference view and must never impersonate 3D output.
    property bool recordedCorridorMode: false
    property real recordedProgress: 0
    readonly property bool exploreReady: root.exploreMode
                                        && ((root.recordedCorridorMode
                                             && root.recordedFrameCount > 0)
                                            || (gaussianView.ready
                                                && !gaussianView.loading
                                                && gaussianView.errorString.length === 0))

    onActiveRouteTileIndexChanged: Qt.callLater(root.preloadAdjacentRouteTiles)
    onRouteTilesChanged: {
        root.activeRouteTileIndex = 0;
        root.pendingRouteFrame = -1;
        if (root.exploreMode)
            Qt.callLater(root.preloadAdjacentRouteTiles);
    }

    onSelectedPlyPathChanged: {
        if (root.selectedPlyPath.length === 0)
            root.exploreMode = false;
        root.driveMode = false;
        root.carlaDriveMode = false;
        root.pendingDriveStart = false;
        root.activeRouteTileIndex = 0;
        root.pendingRouteFrame = -1;
        root.recordedCorridorMode = false;
        root.recordedProgress = 0;
        root.loadNativePhysics();
    }
    onExploreModeChanged: {
        if (!root.exploreMode) {
            root.stopMovement();
            root.driveMode = false;
            root.carlaDriveMode = false;
            NativeVehicleController.stop();
        }
        if (root.exploreMode)
            Qt.callLater(root.preloadAdjacentRouteTiles);
    }
    onSelectedWorldIdChanged: {
        root.loadNativePhysics();
        root.carlaDriveMode = false;
        root.pendingDriveStart = false;
        SimulationController.refreshWorldExecution(root.selectedWorldId);
    }

    function resetLayout() {
        Session.viewportFocusMode = false;
        root.detailsVisible = false;
        worldLibrary.SplitView.preferredWidth = 330;
        worldInspector.SplitView.preferredWidth = 360;
    }

    function stopMovement() {
        root.moveForward = false;
        root.moveBackward = false;
        root.moveLeft = false;
        root.moveRight = false;
        root.moveUp = false;
        root.moveDown = false;
    }

    function toggleExplore() {
        if (!root.hasSelection || root.selectedPlyPath.length === 0)
            return;
        root.exploreMode = !root.exploreMode;
        if (root.exploreMode) {
            root.recordedCorridorMode = false;
            root.recordedProgress = 0;
            gaussianView.followPath = true;
            gaussianView.forceActiveFocus();
        } else {
            root.stopMovement();
        }
    }

    function loadNativePhysics() {
        if (!root.hasSelection || root.selectedWorldPath.length === 0) {
            NativeVehicleController.stop();
            return false;
        }
        if (NativeVehicleController.worldId === root.selectedWorldId
                && NativeVehicleController.ready)
            return true;
        return NativeVehicleController.loadWorld(root.selectedWorldPath);
    }

    function launchReferenceDrive() {
        if (!root.loadNativePhysics()) {
            root.noticeText = NativeVehicleController.errorString;
            noticeTimer.restart();
            return;
        }
        root.exploreMode = true;
        root.recordedCorridorMode = false;
        root.driveMode = true;
        gaussianView.followPath = false;
        NativeVehicleController.start();
        Qt.callLater(function() { liveDrive.forceActiveFocus(); });
    }

    function startReferenceDrive() {
        if (NativeVehicleController.running) {
            root.exploreMode = true;
            root.recordedCorridorMode = false;
            root.driveMode = true;
            Qt.callLater(function() { liveDrive.forceActiveFocus(); });
            return;
        }
        root.launchReferenceDrive();
    }

    function showLatestDrive() {
        root.startCarlaDrive(false);
    }

    function carlaCamera(sensorId, yawSign) {
        return {
            sensor_id: sensorId,
            kind: "rgb",
            mount_vehicle: {
                position: {x: 1.5, y: 0.0, z: 1.4},
                orientation: {
                    w: 0.9914448613738104,
                    x: 0.0,
                    y: 0.0,
                    z: 0.13052619222005157 * yawSign
                }
            },
            intrinsics: {
                width: 960, height: 540,
                horizontal_fov_deg: 90.0,
                fx: 480.0, fy: 480.0, cx: 480.0, cy: 270.0
            },
            sensor_tick_seconds: 0.05
        };
    }

    function carlaConfiguration() {
        return {
            world_execution_manifest: SimulationController.executionManifestPath,
            route_id: "primary",
            vehicle: {
                blueprint: "vehicle.lincoln.mkz_2020",
                physics_configuration: "carla-default",
                spawn_height_offset_m: 0.25
            },
            policy: {
                adapter: "external-driving",
                name: "Local DriveMA-2B (Qwen3.5-2B)",
                adapter_version: "official-drivema-two-turn/v1",
                checkpoint_uri: ReconstructionController.runtimePath
                                + "/../checkpoints/DriveMA-2B/model.safetensors",
                checkpoint_sha256: "sha256:f7342f9c1dd3b32f61ace5ee3f582f2eb8bea4aca9212fd879a4a3ce2dbfc3a8",
                oracle: false,
                uses_privileged_state: false,
                trainable: false,
                eligible_for_promotion: false,
                input_camera_ids: ["front_left", "front", "front_right"],
                uses_ego_speed: true,
                uses_ego_acceleration: true,
                uses_recent_ego_poses: true,
                uses_previous_action: true
            },
            observation: {
                source: "servo-gaussian",
                renderer_version: "servo-headless-gsplat-live-camera/v3",
                camera: {
                    sensor_id: "front",
                    kind: "rgb",
                    mount_vehicle: {
                        position: {x: 1.5, y: 0.0, z: 1.4},
                        orientation: {w: 1.0, x: 0.0, y: 0.0, z: 0.0}
                    },
                    intrinsics: {
                        width: 960, height: 540,
                        horizontal_fov_deg: 90.0,
                        fx: 480.0, fy: 480.0, cx: 480.0, cy: 270.0
                    },
                    sensor_tick_seconds: 0.05
                },
                additional_cameras: [
                    root.carlaCamera("front_left", -1.0),
                    root.carlaCamera("front_right", 1.0)
                ],
                record_policy_frames: true
            },
            scenario: {
                seed: 42,
                maximum_duration_s: 45.0,
                weather: Session.worldWeather === "snow" ? "snow" : "clear",
                snow_accumulation: Session.worldSnowAccumulation,
                dynamic_actor_profile: "none"
            },
            timing: {
                fixed_delta_seconds: 0.05,
                policy_hz: 1,
                sensor_hz: 20,
                policy_deadline_ms: 30000.0
            },
            recording: {
                save_policy_frames: true,
                save_every_nth_frame: 1,
                encode_preview_video: true,
                maximum_saved_frames: 600,
                run_roadside_detection: false
            },
            resource_profile: "balanced"
        };
    }

    function beginPendingCarlaRun() {
        if (!root.pendingDriveStart || !SimulationController.online
                || !SimulationController.executionReady
                || SimulationController.executionManifestPath.length === 0
                || SimulationController.executionWorldId !== root.selectedWorldId
                || SimulationController.busy)
            return;
        root.pendingDriveStart = false;
        if (SimulationController.hasSession && SimulationController.terminal)
            SimulationController.forgetSimulation();
        SimulationController.clearError();
        SimulationController.startSimulation(root.carlaConfiguration());
    }

    function startCarlaDrive(forceNew) {
        if (!root.hasSelection || !root.selectedWorldPublished) {
            root.noticeText = "Select a published Gaussian world before starting CARLA.";
            noticeTimer.restart();
            return;
        }
        NativeVehicleController.stop();
        root.driveMode = false;
        root.exploreMode = true;
        root.recordedCorridorMode = false;
        root.carlaDriveMode = true;

        const matchingSession = SimulationController.hasSession
                                && SimulationController.selectedWorldId === root.selectedWorldId;
        if (!forceNew && matchingSession)
            return;
        if (SimulationController.hasSession && !SimulationController.terminal) {
            root.noticeText = matchingSession
                    ? "The physical CARLA run is already active."
                    : "Stop the active CARLA session before driving another world.";
            noticeTimer.restart();
            return;
        }
        root.pendingDriveStart = true;
        if (!SimulationController.online)
            SimulationController.connectToServer();
        SimulationController.refreshWorldExecution(root.selectedWorldId);
        root.beginPendingCarlaRun();
    }

    function activateAttachedDrive() {
        if (!NativeVehicleController.running || !root.hasSelection
                || NativeVehicleController.worldId !== root.selectedWorldId)
            return;
        root.exploreMode = true;
        root.recordedCorridorMode = false;
        root.driveMode = true;
    }

    function routeTileUrl(index) {
        if (index < 0 || index >= root.routeTiles.length)
            return "";
        return String(root.routeTiles[index].plyPath || "");
    }

    function routeFrameForTile(index, localProgress) {
        if (index < 0 || index >= root.routeTiles.length)
            return 0;
        const tile = root.routeTiles[index];
        const start = Number(tile.cameraStart || 0);
        const count = Math.max(1, Number(tile.cameraCount || 1));
        return start + Math.max(0, Math.min(1, localProgress)) * (count - 1);
    }

    function tileProgressForFrame(index, frame) {
        if (index < 0 || index >= root.routeTiles.length)
            return 0;
        const tile = root.routeTiles[index];
        const start = Number(tile.cameraStart || 0);
        const count = Math.max(1, Number(tile.cameraCount || 1));
        return Math.max(0, Math.min(1, (frame - start) / Math.max(1, count - 1)));
    }

    function routeTileForFrame(frame) {
        if (root.routeTiles.length < 2)
            return 0;
        for (let index = 0; index + 1 < root.routeTiles.length; ++index) {
            const currentEnd = Number(root.routeTiles[index].cameraEndExclusive || 1) - 1;
            const nextStart = Number(root.routeTiles[index + 1].cameraStart || 0);
            const overlapMidpoint = (currentEnd + nextStart) * 0.5;
            if (frame < overlapMidpoint)
                return index;
        }
        return root.routeTiles.length - 1;
    }

    function preloadAdjacentRouteTiles() {
        if (!root.exploreMode || root.routeTiles.length < 2)
            return;
        const previous = root.routeTileUrl(root.activeRouteTileIndex - 1);
        const next = root.routeTileUrl(root.activeRouteTileIndex + 1);
        if (previous.length > 0)
            gaussianView.preloadSource(previous);
        if (next.length > 0)
            gaussianView.preloadSource(next);
    }

    function selectRouteTile(index, routeFrame, preserveMotion) {
        if (root.routeTiles.length < 2)
            return;
        const nextIndex = Math.max(0, Math.min(root.routeTiles.length - 1, index));
        if (nextIndex === root.activeRouteTileIndex)
            return;
        if (!preserveMotion)
            root.stopMovement();
        root.recordedCorridorMode = false;
        root.pendingRouteFrame = Number.isFinite(routeFrame) ? routeFrame : -1;
        root.activeRouteTileIndex = nextIndex;
        gaussianView.followPath = true;
        Qt.callLater(function() {
            root.preloadAdjacentRouteTiles();
            gaussianView.forceActiveFocus();
        });
    }

    function updateAutomaticRouteTile() {
        if (!root.automaticRouteStreaming || root.routeTiles.length < 2
                || !root.exploreMode || gaussianView.loading || !gaussianView.ready)
            return;
        let frame = 0;
        if (root.driveMode && NativeVehicleController.running) {
            frame = Math.max(0, Math.min(1, NativeVehicleController.routeCompletion))
                    * (root.routeFrameCount - 1);
        } else if (gaussianView.followPath) {
            frame = root.routeFrameForTile(root.activeRouteTileIndex,
                                           gaussianView.pathProgress);
        } else {
            return;
        }
        const target = root.routeTileForFrame(frame);
        if (target !== root.activeRouteTileIndex)
            root.selectRouteTile(target, frame, true);
    }

    function syncCarlaWorldRoute() {
        if (!root.carlaDriveMode || !carlaDrive.worldView
                || !root.exploreMode || root.routeTiles.length < 1
                || gaussianView.loading || !gaussianView.ready)
            return;
        const progress = Math.max(0, Math.min(
            1, Number(carlaDrive.displayedWorldProgress || 0)));
        const frame = progress * (root.routeFrameCount - 1);
        const target = root.routeTileForFrame(frame);
        if (target !== root.activeRouteTileIndex) {
            root.selectRouteTile(target, frame, true);
            return;
        }
        gaussianView.followPath = true;
        gaussianView.setPathProgress(root.tileProgressForFrame(target, frame));
    }

    Connections {
        target: Session
        function onAssistantActionRequested(action, argument) {
            if (action === "explore-world") {
                const match = String(argument).toLowerCase();
                if (WorldLibraryModel.selectWorldMatching(match)) {
                    root.exploreMode = true;
                    root.recordedCorridorMode = false;
                    gaussianView.followPath = true;
                    gaussianView.forceActiveFocus();
                }
            }
        }
    }

    Connections {
        target: NativeVehicleController
        function onStateChanged() {
            if (NativeVehicleController.running)
                root.activateAttachedDrive();
            else if (root.driveMode)
                root.driveMode = false;
        }
    }

    Connections {
        target: SimulationController

        function onConfigurationChanged() {
            root.beginPendingCarlaRun();
        }

        function onConnectionChanged() {
            root.beginPendingCarlaRun();
        }

        function onSessionChanged() {
            if (SimulationController.hasSession
                    && SimulationController.selectedWorldId === root.selectedWorldId) {
                root.exploreMode = true;
                root.carlaDriveMode = true;
            }
            if (SimulationController.sessionState === "failed") {
                root.noticeText = SimulationController.lastError.length > 0
                        ? SimulationController.lastError
                        : "The CARLA simulation failed. Open the session evidence for details.";
                noticeTimer.restart();
            }
        }
    }

    function sortIndex(mode) {
        if (mode === "name")
            return 1;
        if (mode === "size")
            return 2;
        return 0;
    }

    function metricText(value, digits) {
        const number = Number(value);
        return Number.isFinite(number) && number >= 0 ? number.toFixed(digits) : "—";
    }

    function visualizationDescription(mode) {
        if (mode === 1)
            return "False-color relative camera depth inferred from the Gaussian field; this is not LiDAR or metres without a scale anchor.";
        if (mode === 2)
            return "Shortest-axis splat orientation exposes structural inconsistency; it is a diagnostic cue, not a collision surface normal.";
        if (mode === 3)
            return "Accumulated opacity support: dark areas are gaps, weak evidence, or unseen space and must not be treated as drivable.";
        return "Photometric Gaussian appearance for visual review; good RGB alone does not prove road geometry or autonomy safety.";
    }

    function openRenameDialog() {
        if (!root.hasSelection)
            return;
        renameDialog.worldId = String(root.selectedWorld.worldId);
        renameField.text = String(root.selectedWorld.displayName);
        renameDialog.open();
        renameField.forceActiveFocus();
        renameField.selectAll();
    }

    function openDeleteDialog() {
        if (!root.hasSelection)
            return;
        deleteDialog.worldId = String(root.selectedWorld.worldId);
        deleteDialog.worldName = String(root.selectedWorld.displayName);
        deleteDialog.storageText = String(root.selectedWorld.sizeText);
        deleteDialog.open();
    }

    Settings {
        id: layoutSettings
        category: "WorldEditorLayout"
        property var horizontalSplitState
        property int layoutSchema: 0
    }

    Timer {
        id: noticeTimer
        interval: 5000
        onTriggered: root.noticeText = ""
    }

    // Deterministic app-level verification hook. It follows the same public
    // load/start path as the Drive world button and never bypasses validation.
    Timer {
        interval: 250
        repeat: true
        running: root.nativeDriveSmoke && !NativeVehicleController.running
        onTriggered: {
            if (!root.hasSelection)
                return;
            if (root.loadNativePhysics()) {
                stop();
                root.startReferenceDrive();
            }
        }
    }

    Timer {
        id: routeStreamingTimer
        interval: 80
        repeat: true
        running: root.exploreMode && root.routeTiles.length > 1
        onTriggered: root.updateAutomaticRouteTile()
    }

    Timer {
        interval: 80
        repeat: true
        running: root.carlaDriveMode && carlaDrive.worldView
                 && root.exploreMode && root.routeTiles.length > 0
        onTriggered: root.syncCarlaWorldRoute()
    }

    FrameAnimation {
        running: root.exploreReady
                 && !root.driveMode
                 && (root.moveForward || root.moveBackward
                     || root.moveLeft || root.moveRight
                     || root.moveUp || root.moveDown)
        onTriggered: {
            const elapsed = Math.min(frameTime, 0.05);
            const forward = (root.moveForward ? 1 : 0)
                            - (root.moveBackward ? 1 : 0);
            if (root.recordedCorridorMode) {
                root.recordedProgress = Math.max(
                    0, Math.min(1, root.recordedProgress + forward * elapsed * 0.12));
            } else {
                gaussianView.moveCamera(
                    forward,
                    (root.moveRight ? 1 : 0) - (root.moveLeft ? 1 : 0),
                    (root.moveUp ? 1 : 0) - (root.moveDown ? 1 : 0),
                    elapsed);
            }
        }
    }

    Shortcut {
        sequence: "Ctrl+E"
        enabled: root.hasSelection && root.selectedPlyPath.length > 0
        onActivated: root.toggleExplore()
    }

    Shortcut {
        sequence: "Ctrl+D"
        enabled: root.hasSelection
        onActivated: root.startCarlaDrive(false)
    }

    onVisibleChanged: {
        if (!visible)
            root.stopMovement();
    }

    Component.onCompleted: {
        if (layoutSettings.layoutSchema === 1
                && layoutSettings.horizontalSplitState !== undefined) {
            worldSplit.restoreState(layoutSettings.horizontalSplitState);
        } else {
            root.resetLayout();
            layoutSettings.layoutSchema = 1;
        }
        WorldLibraryModel.refresh();
        if (Qt.application.arguments.indexOf("--native-snow-smoke") >= 0)
            Session.worldWeather = "snow";
        root.loadNativePhysics();
        root.activateAttachedDrive();
        SimulationController.connectToServer();
        SimulationController.refreshWorldExecution(root.selectedWorldId);
    }

    Component.onDestruction: {
        if (!Session.viewportFocusMode)
            layoutSettings.horizontalSplitState = worldSplit.saveState();
    }

    Connections {
        target: Session

        function onResetWorkspaceLayoutRequested() {
            root.resetLayout();
        }
    }

    Connections {
        target: WorldLibraryModel

        function onWorldDeleted(worldId, displayName, recoveredBytes) {
            root.noticeText = displayName + " was deleted. "
                              + root.metricStorage(recoveredBytes) + " recovered.";
            noticeTimer.restart();
        }
    }

    function metricStorage(bytes) {
        const value = Number(bytes);
        if (!Number.isFinite(value) || value < 0)
            return "Storage";
        const units = ["B", "KiB", "MiB", "GiB", "TiB"];
        let scaled = value;
        let unit = 0;
        while (scaled >= 1024 && unit < units.length - 1) {
            scaled /= 1024;
            ++unit;
        }
        return (unit === 0 ? Math.round(scaled).toString()
                           : scaled.toFixed(scaled < 10 ? 2 : 1)) + " " + units[unit];
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "Worlds"
            helpText: "Every accepted reconstruction lands here as a durable, hash-verified bundle: Gaussians, cameras, receipts and audit media. Open a world in the native Vulkan viewer or feed it to campaigns as run background."
            subtitle: WorldLibraryModel.busy
                      ? WorldLibraryModel.busyText
                      : (WorldLibraryModel.totalCount + " created · "
                         + WorldLibraryModel.totalBytesText + " local")
            iconSource: Theme.icon("world")
            Layout.fillWidth: true

            TextButton {
                text: "Details"
                iconSource: Theme.icon("inspector")
                compact: true
                selected: root.detailsVisible
                enabled: root.hasSelection && !Session.viewportFocusMode
                toolTip: root.detailsVisible ? "Hide world details" : "Show world details"
                onClicked: root.detailsVisible = !root.detailsVisible
            }

            TextButton {
                text: "Create world"
                iconSource: Theme.icon("plus")
                tone: "primary"
                onClicked: Session.workspaceIndex = 0
            }

            TextButton {
                text: "Refresh"
                iconSource: Theme.icon("refresh")
                enabled: !WorldLibraryModel.busy
                onClicked: WorldLibraryModel.refresh()
            }
        }

        Rectangle {
            visible: WorldLibraryModel.lastError.length > 0 || root.noticeText.length > 0
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 38 : 0
            color: WorldLibraryModel.lastError.length > 0
                   ? Theme.tintError : Theme.tintSuccess

            Behavior on color {
                ColorAnimation {
                    duration: Theme.animBase
                }
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 11
                anchors.rightMargin: 5
                spacing: 8

                SvgIcon {
                    source: Theme.icon(WorldLibraryModel.lastError.length > 0
                                       ? "error" : "check")
                    iconSize: Theme.iconSm
                    color: WorldLibraryModel.lastError.length > 0
                           ? Theme.error : Theme.success
                }
                Text {
                    Layout.fillWidth: true
                    text: WorldLibraryModel.lastError.length > 0
                          ? WorldLibraryModel.lastError : root.noticeText
                    color: WorldLibraryModel.lastError.length > 0
                           ? Theme.error : Theme.success
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }
                IconButton {
                    iconSource: Theme.icon("close")
                    buttonSize: 24
                    toolTip: "Dismiss"
                    onClicked: {
                        WorldLibraryModel.clearLastError();
                        root.noticeText = "";
                    }
                }
            }
        }

        SplitView {
            id: worldSplit
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: SplitHandle {}

            Panel {
                id: worldLibrary
                visible: !Session.viewportFocusMode
                SplitView.preferredWidth: 330
                SplitView.minimumWidth: 270
                SplitView.maximumWidth: 520

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Created worlds"
                        subtitle: WorldLibraryModel.filterText.length > 0
                                  ? (WorldLibraryModel.count + " / "
                                     + WorldLibraryModel.totalCount)
                                  : WorldLibraryModel.totalCount.toString()
                        iconSource: Theme.icon("folder")
                        actionIcon: Theme.icon("refresh")
                        actionToolTip: "Rescan local worlds"
                        onActionTriggered: WorldLibraryModel.refresh()
                        Layout.fillWidth: true
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 42
                        Layout.minimumHeight: 42
                        Layout.maximumHeight: 42
                        Layout.leftMargin: 7
                        Layout.rightMargin: 7
                        spacing: 6

                        SearchField {
                            Layout.fillWidth: true
                            hint: "Search worlds"
                            text: WorldLibraryModel.filterText
                            onTextChanged: WorldLibraryModel.filterText = text
                        }

                        SelectField {
                            Layout.preferredWidth: 92
                            Layout.preferredHeight: Theme.controlHeight
                            Layout.fillHeight: false
                            model: ["Newest", "Name", "Largest"]
                            currentIndex: root.sortIndex(WorldLibraryModel.sortMode)
                            onActivated: {
                                WorldLibraryModel.sortMode = currentIndex === 1
                                                             ? "name"
                                                             : (currentIndex === 2
                                                                ? "size" : "newest");
                            }
                        }
                    }

                    ListView {
                        id: worldList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: WorldLibraryModel
                        visible: count > 0 || WorldLibraryModel.busy
                        currentIndex: WorldLibraryModel.selectedIndex
                        boundsBehavior: Flickable.StopAtBounds
                        spacing: 1
                        reuseItems: true
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        delegate: Item {
                            id: worldDelegate

                            required property int index
                            required property string worldId
                            required property string displayName
                            required property string sourceSummary
                            required property string createdText
                            required property string sizeText
                            required property string gaussianText
                            required property string qualityLabel
                            required property string qualityTone
                            required property url previewUrl
                            required property bool published

                            readonly property bool isSelected:
                                worldDelegate.worldId === WorldLibraryModel.selectedWorldId

                            width: worldList.width
                            height: 96
                            activeFocusOnTab: true
                            Accessible.role: Accessible.ListItem
                            Accessible.name: worldDelegate.displayName
                            Accessible.description: worldDelegate.gaussianText + " splats, "
                                                    + worldDelegate.qualityLabel
                            Accessible.focusable: true
                            Accessible.onPressAction: WorldLibraryModel.selectWorld(
                                                          worldDelegate.worldId)

                            Keys.onPressed: event => {
                                if (event.key === Qt.Key_Return
                                        || event.key === Qt.Key_Enter
                                        || event.key === Qt.Key_Space) {
                                    WorldLibraryModel.selectWorld(worldDelegate.worldId);
                                    event.accepted = true;
                                }
                            }

                            Rectangle {
                                anchors.fill: parent
                                anchors.margins: 3
                                radius: Theme.cornerCard - 2
                                color: worldDelegate.isSelected ? Theme.selection : (worldArea.containsMouse ? Theme.panelRaised : "transparent")

                                Behavior on color {
                                    ColorAnimation {
                                        duration: Theme.animFast
                                        easing.type: Easing.OutCubic
                                    }
                                }
                            }

                            Rectangle {
                                visible: worldDelegate.isSelected
                                anchors.left: parent.left
                                anchors.leftMargin: 5
                                anchors.verticalCenter: parent.verticalCenter
                                width: 3
                                height: 40
                                radius: 1.5
                                color: Theme.accent

                                Behavior on opacity {
                                    NumberAnimation {
                                        duration: Theme.animBase
                                    }
                                }
                            }

                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 10

                                Rectangle {
                                    Layout.preferredWidth: 68
                                    Layout.preferredHeight: 68
                                    Layout.alignment: Qt.AlignVCenter
                                    color: Theme.viewport
                                    radius: Theme.cornerTile
                                    clip: true

                                    Image {
                                        anchors.fill: parent
                                        source: worldDelegate.previewUrl
                                        visible: source.toString().length > 0
                                        asynchronous: true
                                        cache: true
                                        fillMode: Image.PreserveAspectCrop
                                        sourceSize.width: 240
                                    }

                                    SvgIcon {
                                        anchors.centerIn: parent
                                        visible: worldDelegate.previewUrl.toString().length === 0
                                        source: Theme.icon("world")
                                        iconSize: 20
                                        color: Theme.textDisabled
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    spacing: 3

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 5
                                        Text {
                                            Layout.fillWidth: true
                                            text: worldDelegate.displayName
                                            color: Theme.text
                                            font.family: Theme.uiFont
                                            font.pixelSize: 11
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideRight
                                        }
                                        StatusBadge {
                                            text: worldDelegate.qualityLabel
                                            tone: worldDelegate.qualityTone
                                        }
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: worldDelegate.sourceSummary
                                        color: Theme.textMuted
                                        font.family: Theme.uiFont
                                        font.pixelSize: 9
                                        elide: Text.ElideMiddle
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: worldDelegate.published
                                              ? worldDelegate.gaussianText + " splats · "
                                                + worldDelegate.sizeText
                                              : "No PLY — quality gate failed · "
                                                + worldDelegate.sizeText
                                        color: Theme.textSecondary
                                        font.family: Theme.monoFont
                                        font.pixelSize: 9
                                        elide: Text.ElideRight
                                    }

                                    Item {
                                        Layout.fillHeight: true
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: worldDelegate.createdText
                                        color: Theme.textDisabled
                                        font.family: Theme.uiFont
                                        font.pixelSize: 9
                                        elide: Text.ElideRight
                                    }
                                }
                            }

                            MouseArea {
                                id: worldArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: WorldLibraryModel.selectWorld(worldDelegate.worldId)
                            }
                        }
                    }

                    EmptyState {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: worldList.count === 0 && !WorldLibraryModel.busy
                        iconSource: Theme.icon("world")
                        title: WorldLibraryModel.filterText.length > 0
                               ? "No matching worlds" : "No created worlds"
                        description: WorldLibraryModel.filterText.length > 0
                                     ? "Change the search text to show more worlds."
                                      : "Published worlds and failed diagnostic runs appear here automatically."
                        actionText: WorldLibraryModel.filterText.length > 0
                                    ? "Clear search" : "Create world"
                        actionIcon: WorldLibraryModel.filterText.length > 0
                                    ? Theme.icon("close") : Theme.icon("plus")
                        onActionRequested: {
                            if (WorldLibraryModel.filterText.length > 0)
                                WorldLibraryModel.filterText = "";
                            else
                                Session.workspaceIndex = 0;
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        color: "transparent"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 10
                            spacing: 7
                            SvgIcon {
                                source: Theme.icon("storage")
                                iconSize: Theme.iconSm
                                color: Theme.textDisabled
                            }
                            Text {
                                text: WorldLibraryModel.totalBytesText + " used by completed jobs"
                                color: Theme.textMuted
                                font.family: Theme.uiFont
                                font.pixelSize: 9
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                            LoadingState {
                                visible: WorldLibraryModel.busy
                                running: WorldLibraryModel.busy
                                showElapsed: false
                                label: "Refreshing"
                                variant: "Drive"
                            }
                        }
                    }
                }
            }

            Panel {
                id: previewPanel
                SplitView.fillWidth: true
                SplitView.minimumWidth: 440
                color: Theme.viewport

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        color: Theme.chrome

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 8
                            spacing: 10

                            Text {
                                Layout.fillWidth: false
                                // Long world names must yield space to the primary actions.
                                // Without an explicit zero minimum, RowLayout treats the
                                // text's full implicit width as mandatory and pushes Explore,
                                // CARLA, and bundle controls outside the window.
                                Layout.minimumWidth: 80
                                Layout.preferredWidth: Math.min(300, implicitWidth)
                                Layout.maximumWidth: 300
                                text: root.hasSelection
                                      ? String(root.selectedWorld.displayName)
                                      : "No world selected"
                                color: root.hasSelection ? Theme.text : Theme.textMuted
                                font.family: Theme.uiFont
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            TextButton {
                                visible: root.hasSelection
                                compact: true
                                text: root.exploreMode ? "Validation" : "Explore"
                                iconSource: Theme.icon(root.exploreMode ? "image" : "play")
                                tone: root.selectedPlyPath.length > 0 && !root.exploreMode ? "primary" : "default"
                                enabled: root.selectedPlyPath.length > 0
                                onClicked: root.toggleExplore()
                            }
                            TextButton {
                                visible: root.hasSelection
                                compact: true
                                text: SimulationController.busy ? "Starting CARLA"
                                      : (SimulationController.hasSession
                                         && SimulationController.selectedWorldId === root.selectedWorldId
                                         ? (SimulationController.terminal ? "Replay CARLA" : "CARLA live")
                                         : "Drive CARLA")
                                iconSource: Theme.icon("play")
                                tone: root.carlaDriveMode ? "primary" : "default"
                                enabled: root.selectedWorldPublished && !SimulationController.busy
                                toolTip: "Run or replay the real CARLA 0.9.16 Lincoln physics session attached to this world record. CARLA and T5 remain separate views."
                                onClicked: root.startCarlaDrive(false)
                            }
                            TextButton {
                                visible: root.hasSelection
                                compact: true
                                text: root.selectedWorldPublished ? "Open bundle" : "Open job"
                                iconSource: Theme.icon("folder")
                                onClicked: {
                                    if (root.selectedWorldPublished)
                                        WorldLibraryModel.openWorldFolder(
                                                    String(root.selectedWorld.worldId));
                                    else
                                        WorldLibraryModel.openJobFolder(
                                                    String(root.selectedWorld.worldId));
                                }
                            }
                            IconButton {
                                iconSource: Theme.icon(Session.viewportFocusMode
                                                      ? "minimize" : "maximize")
                                toolTip: Session.viewportFocusMode
                                         ? "Restore library and inspector"
                                         : "Focus preview"
                                selected: Session.viewportFocusMode
                                buttonSize: 24
                                onClicked: Session.viewportFocusMode = !Session.viewportFocusMode
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                            }
                        }

                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        Rectangle {
                            anchors.fill: parent
                            color: Theme.viewport

                            Image {
                                id: validationPreview
                                anchors.fill: parent
                                anchors.margins: 18
                                source: root.hasSelection
                                        ? root.selectedPreviewUrl : ""
                                visible: root.hasSelection && !root.exploreMode
                                         && source.toString().length > 0
                                asynchronous: true
                                cache: true
                                fillMode: Image.PreserveAspectFit
                                sourceSize.width: 2048
                                sourceSize.height: 1200
                            }

                            EmptyState {
                                anchors.fill: parent
                                visible: !root.hasSelection
                                iconSource: Theme.icon("world")
                                title: "Select a created world"
                                description: "Completed reconstructions load here automatically; no folder drag or manual import is required."
                                actionText: "Create world"
                                actionIcon: Theme.icon("plus")
                                onActionRequested: Session.workspaceIndex = 0
                            }

                            EmptyState {
                                anchors.fill: parent
                                visible: root.hasSelection && !root.exploreMode
                                         && root.selectedPreviewUrl.toString().length === 0
                                iconSource: Theme.icon("image")
                                title: "World bundle loaded"
                                description: "This build has no validation preview image. Its verified Gaussian PLY remains available in the bundle."
                            }

                            GaussianSplatView {
                                id: gaussianView
                                z: 0
                                anchors.top: parent.top
                                anchors.left: parent.left
                                anchors.bottom: parent.bottom
                                width: liveDrive.visible && liveDrive.splitView
                                       ? Math.floor(parent.width / 2) : parent.width
                                visible: root.hasSelection && root.exploreMode
                                         && (!root.carlaDriveMode
                                             || carlaDrive.worldView)
                                source: root.hasSelection ? root.explorePlyPath : ""
                                visualizationMode: root.visualizationMode
                                snowAccumulation: root.snowAccumulation
                                focus: visible
                                onReadyChanged: {
                                    if (!ready || loading)
                                        return;
                                    if (root.pendingRouteFrame >= 0) {
                                        const targetProgress = root.tileProgressForFrame(
                                            root.activeRouteTileIndex,
                                            root.pendingRouteFrame);
                                        root.pendingRouteFrame = -1;
                                        gaussianView.setPathProgress(targetProgress);
                                    }
                                    root.preloadAdjacentRouteTiles();
                                }
                                onActiveFocusChanged: {
                                    if (!activeFocus)
                                        root.stopMovement();
                                }

                                Keys.onPressed: event => {
                                    if (root.driveMode) {
                                        if (event.isAutoRepeat)
                                            return;
                                        if (event.key === Qt.Key_W || event.key === Qt.Key_Up)
                                            NativeVehicleController.setInput("forward", true);
                                        else if (event.key === Qt.Key_S || event.key === Qt.Key_Down)
                                            NativeVehicleController.setInput("reverse", true);
                                        else if (event.key === Qt.Key_A || event.key === Qt.Key_Left)
                                            NativeVehicleController.setInput("left", true);
                                        else if (event.key === Qt.Key_D || event.key === Qt.Key_Right)
                                            NativeVehicleController.setInput("right", true);
                                        else if (event.key === Qt.Key_Space)
                                            NativeVehicleController.setInput("brake", true);
                                        else if (event.key === Qt.Key_R)
                                            NativeVehicleController.reset();
                                        else
                                            return;
                                        event.accepted = true;
                                        return;
                                    }
                                    if (event.key === Qt.Key_W || event.key === Qt.Key_Up)
                                        root.moveForward = true;
                                    else if (event.key === Qt.Key_S || event.key === Qt.Key_Down)
                                        root.moveBackward = true;
                                    else if (event.key === Qt.Key_A || event.key === Qt.Key_Left)
                                        root.moveLeft = true;
                                    else if (event.key === Qt.Key_D || event.key === Qt.Key_Right)
                                        root.moveRight = true;
                                    else if (event.key === Qt.Key_E || event.key === Qt.Key_Space)
                                        root.moveUp = true;
                                    else if (event.key === Qt.Key_Q || event.key === Qt.Key_Control)
                                        root.moveDown = true;
                                    else if (event.key === Qt.Key_R) {
                                        root.recordedProgress = 0;
                                        gaussianView.resetCamera();
                                    }
                                    else if (event.key === Qt.Key_1)
                                        root.visualizationMode = 0;
                                    else if (event.key === Qt.Key_2)
                                        root.visualizationMode = 1;
                                    else if (event.key === Qt.Key_3)
                                        root.visualizationMode = 2;
                                    else if (event.key === Qt.Key_4)
                                        root.visualizationMode = 3;
                                    else if (event.key === Qt.Key_Escape)
                                        root.exploreMode = false;
                                    else
                                        return;
                                    event.accepted = true;
                                }

                                Keys.onReleased: event => {
                                    if (event.isAutoRepeat)
                                        return;
                                    if (root.driveMode) {
                                        if (event.key === Qt.Key_W || event.key === Qt.Key_Up)
                                            NativeVehicleController.setInput("forward", false);
                                        else if (event.key === Qt.Key_S || event.key === Qt.Key_Down)
                                            NativeVehicleController.setInput("reverse", false);
                                        else if (event.key === Qt.Key_A || event.key === Qt.Key_Left)
                                            NativeVehicleController.setInput("left", false);
                                        else if (event.key === Qt.Key_D || event.key === Qt.Key_Right)
                                            NativeVehicleController.setInput("right", false);
                                        else if (event.key === Qt.Key_Space)
                                            NativeVehicleController.setInput("brake", false);
                                        else
                                            return;
                                        event.accepted = true;
                                        return;
                                    }
                                    if (event.key === Qt.Key_W || event.key === Qt.Key_Up)
                                        root.moveForward = false;
                                    else if (event.key === Qt.Key_S || event.key === Qt.Key_Down)
                                        root.moveBackward = false;
                                    else if (event.key === Qt.Key_A || event.key === Qt.Key_Left)
                                        root.moveLeft = false;
                                    else if (event.key === Qt.Key_D || event.key === Qt.Key_Right)
                                        root.moveRight = false;
                                    else if (event.key === Qt.Key_E || event.key === Qt.Key_Space)
                                        root.moveUp = false;
                                    else if (event.key === Qt.Key_Q || event.key === Qt.Key_Control)
                                        root.moveDown = false;
                                    else
                                        return;
                                    event.accepted = true;
                                }

                                MouseArea {
                                    property real previousX: 0
                                    property real previousY: 0
                                    anchors.fill: parent
                                    acceptedButtons: Qt.LeftButton
                                    enabled: !root.recordedCorridorMode && !root.driveMode
                                    hoverEnabled: true
                                    cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                                    onPressed: mouse => {
                                        previousX = mouse.x;
                                        previousY = mouse.y;
                                        gaussianView.forceActiveFocus();
                                    }
                                    onPositionChanged: mouse => {
                                        if (!pressed)
                                            return;
                                        gaussianView.look(mouse.x - previousX,
                                                          mouse.y - previousY);
                                        previousX = mouse.x;
                                        previousY = mouse.y;
                                    }
                                    onWheel: wheel => {
                                        gaussianView.changeMovementSpeed(wheel.angleDelta.y / 120.0);
                                        wheel.accepted = true;
                                    }
                                }
                            }

                            LiveDriveView {
                                id: liveDrive
                                z: 5
                                anchors.fill: parent
                                visible: root.hasSelection && root.exploreMode
                                         && !root.carlaDriveMode
                                         && root.driveMode && NativeVehicleController.running
                                active: visible
                                gaussianView: gaussianView
                                snowAccumulation: root.snowAccumulation
                            }

                            CarlaDriveView {
                                id: carlaDrive
                                z: 8
                                anchors.fill: parent
                                visible: root.hasSelection && root.exploreMode
                                         && root.carlaDriveMode
                                active: visible
                                onViewModeChanged: root.syncCarlaWorldRoute()
                                onNewRunRequested: (weather, accumulation) => {
                                    Session.worldWeather = weather;
                                    if (weather === "snow")
                                        Session.worldSnowAccumulation = accumulation;
                                    root.startCarlaDrive(true);
                                }
                                onCloseRequested: {
                                    root.carlaDriveMode = false;
                                    root.exploreMode = false;
                                }
                            }

                            Rectangle {
                                z: 1
                                anchors.fill: parent
                                visible: root.exploreReady
                                         && root.recordedCorridorMode
                                         && root.recordedFrameCount > 0
                                color: "black"

                                Image {
                                    anchors.fill: parent
                                    source: root.recordedFrameUrl
                                    asynchronous: true
                                    cache: true
                                    fillMode: Image.PreserveAspectFit
                                    sourceSize.width: 1910
                                    sourceSize.height: 1074
                                }

                                Rectangle {
                                    anchors.top: parent.top
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    anchors.topMargin: 12
                                    width: sourceFidelityLabel.implicitWidth + 22
                                    height: 26
                                    radius: 8
                                    color: Theme.overlayHud
                                    Text {
                                        id: sourceFidelityLabel
                                        anchors.centerIn: parent
                                        text: "RECORDED CORRIDOR · SOURCE FIDELITY · FRAME "
                                              + (root.recordedFrameIndex + 1) + "/"
                                              + root.recordedFrameCount
                                        color: Theme.success
                                        font.family: Theme.monoFont
                                        font.pixelSize: 9
                                        font.weight: Font.DemiBold
                                    }
                                }
                            }

                            Rectangle {
                                z: 2
                                anchors.centerIn: parent
                                width: Math.min(440, parent.width - 48)
                                height: Math.max(112, Math.min(190, overlayStatus.implicitHeight + 66))
                                visible: root.exploreMode
                                         && !root.recordedCorridorMode
                                         && (gaussianView.loading
                                             || gaussianView.errorString.length > 0)
                                color: Theme.overlayHud
                                radius: Theme.cornerPopup

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 14
                                    spacing: 8

                                    LoadingState {
                                        Layout.alignment: Qt.AlignHCenter
                                        visible: gaussianView.loading
                                        running: gaussianView.loading
                                        label: "Loading world"
                                        variant: "Drive"
                                    }

                                    SvgIcon {
                                        Layout.alignment: Qt.AlignHCenter
                                        visible: gaussianView.errorString.length > 0
                                        source: Theme.icon("error")
                                        iconSize: Theme.iconXl
                                        color: Theme.error
                                    }

                                    Text {
                                        id: overlayStatus
                                        Layout.fillWidth: true
                                        text: gaussianView.errorString.length > 0
                                              ? gaussianView.errorString
                                              : gaussianView.statusText
                                        color: gaussianView.errorString.length > 0
                                               ? Theme.error : Theme.text
                                        font.family: Theme.uiFont
                                        font.pixelSize: 10
                                        horizontalAlignment: Text.AlignHCenter
                                        wrapMode: Text.WordWrap
                                        maximumLineCount: 5
                                        elide: Text.ElideRight
                                    }

                                    Rectangle {
                                        id: loadTrack
                                        Layout.fillWidth: true
                                        visible: gaussianView.loading
                                        Layout.preferredHeight: 3
                                        radius: 1.5
                                        color: Theme.panelHover
                                        clip: true

                                        Rectangle {
                                            id: loadRunner
                                            width: parent.width * 0.32
                                            height: parent.height
                                            radius: 1.5
                                            color: Theme.accent

                                            SequentialAnimation on x {
                                                running: gaussianView.loading && Theme.motionEnabled
                                                loops: Animation.Infinite
                                                NumberAnimation {
                                                    from: -loadRunner.width
                                                    to: loadTrack.width
                                                    duration: 1150
                                                    easing.type: Easing.InOutQuad
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            Rectangle {
                                z: 2
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.rightMargin: 12
                                anchors.topMargin: 12
                                width: 232
                                height: Math.min(parent.height - 24,
                                                 exploreControls.implicitHeight + 18)
                                opacity: root.exploreReady && !root.driveMode ? 1 : 0
                                visible: opacity > 0
                                color: Theme.overlayHud
                                radius: Theme.cornerPopup

                                Behavior on opacity {
                                    enabled: Theme.motionEnabled
                                    NumberAnimation { duration: 140; easing.type: Easing.OutCubic }
                                }

                                ColumnLayout {
                                    id: exploreControls
                                    anchors.fill: parent
                                    anchors.margins: 9
                                    spacing: 5
                                    ColumnLayout {
                                        visible: false
                                        Layout.fillWidth: true
                                        spacing: 2
                                        Text {
                                            text: root.recordedCorridorMode
                                                  ? "EXPLORE / CALIBRATED RECORDED CORRIDOR"
                                                  : gaussianView.followPath
                                                  ? "EXPLORE / SMOOTHED OBSERVED CAMERA CORRIDOR"
                                                  : "EXPLORE / FREE FLY (OUTSIDE COVERAGE MAY FAIL)"
                                            color: Theme.textSecondary
                                            font.family: Theme.uiFont
                                            font.pixelSize: 8
                                            font.weight: Font.DemiBold
                                        }
                                        Text {
                                            text: gaussianView.captureEnvelopeStatus
                                                  + " · "
                                                  + (gaussianView.captureEnvelopeScore * 100).toFixed(0)
                                                  + "% camera evidence"
                                            color: gaussianView.captureEnvelopeScore >= 0.75
                                                   ? Theme.success
                                                   : gaussianView.captureEnvelopeScore >= 0.35
                                                     ? Theme.warning : Theme.error
                                            font.family: Theme.monoFont
                                            font.pixelSize: 8
                                            font.weight: Font.DemiBold
                                        }
                                        Text {
                                            text: root.recordedCorridorMode
                                                  ? "W/S moves through original calibrated frames | source sharpness | lateral view disabled"
                                                  : gaussianView.followPath
                                                  ? "W/S follow capture | A/D and E/Q bounded offsets | drag to look | R resets"
                                                  : "WASD free fly | E/Q vertical | drag to look | R resets"
                                            color: Theme.textMuted
                                            font.family: Theme.uiFont
                                            font.pixelSize: 9
                                        }
                                    }
                                    TextButton {
                                        compact: true
                                        visible: root.recordedFrameCount > 1
                                        text: root.recordedCorridorMode
                                              ? "Back to Gaussian 3D" : "Reference frames"
                                        selected: root.recordedCorridorMode
                                        toolTip: root.recordedCorridorMode
                                                 ? "Return to the reconstructed 1.46M-splat world."
                                                 : "Compare against original calibrated video frames. This is reference media, not reconstruction output."
                                        onClicked: {
                                            root.recordedCorridorMode = !root.recordedCorridorMode;
                                            gaussianView.followPath = true;
                                            gaussianView.forceActiveFocus();
                                        }
                                    }
                                    RowLayout {
                                        spacing: 3
                                        Layout.alignment: Qt.AlignHCenter
                                        TextButton {
                                            compact: true
                                            text: "1×"
                                            selected: gaussianView.movementSpeed < 1.5
                                            toolTip: "Precise movement"
                                            onClicked: { gaussianView.movementSpeed = 0.8; gaussianView.forceActiveFocus(); }
                                        }
                                        TextButton {
                                            compact: true
                                            text: "3×"
                                            selected: gaussianView.movementSpeed >= 1.5 && gaussianView.movementSpeed < 4.0
                                            toolTip: "Road exploration speed"
                                            onClicked: { gaussianView.movementSpeed = 2.5; gaussianView.forceActiveFocus(); }
                                        }
                                        TextButton {
                                            compact: true
                                            text: "6×"
                                            selected: gaussianView.movementSpeed >= 4.0
                                            toolTip: "Fast traversal"
                                            onClicked: { gaussianView.movementSpeed = 5.0; gaussianView.forceActiveFocus(); }
                                        }
                                    }
                                    RowLayout {
                                        visible: true
                                        spacing: 3
                                        TextButton { compact: true; text: "Clear"; selected: Session.worldWeather === "clear"; onClicked: Session.worldWeather = "clear" }
                                        TextButton {
                                            compact: true
                                            text: "Snow"
                                            selected: Session.worldWeather === "snow"
                                            toolTip: "Accumulate snow on inferred up-facing Gaussian surfaces and the physical vehicle. Visual snow depth is nonmetric; vehicle grip is reduced in physics."
                                            onClicked: Session.worldWeather = "snow"
                                        }
                                        Slider {
                                            visible: Session.worldWeather === "snow"
                                            Layout.preferredWidth: 110
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
                                    }
                                    TextButton {
                                        compact: true
                                        visible: !root.recordedCorridorMode
                                        enabled: gaussianView.pathAvailable
                                        text: gaussianView.followPath ? "Smoothed path" : "Free fly"
                                        toolTip: gaussianView.followPath
                                                 ? "W/S follows a height-smoothed source-camera path that preserves sustained grades while removing pose bounce."
                                                 : "Free fly can expose unobserved surfaces and is not verified geometry."
                                        onClicked: {
                                            gaussianView.followPath = !gaussianView.followPath;
                                            gaussianView.forceActiveFocus();
                                        }
                                    }
                                    Text {
                                        visible: false
                                        text: gaussianView.gaussianCount.toLocaleString()
                                              + " total splats\n"
                                              + (root.recordedCorridorMode
                                                 ? (root.recordedProgress * 100).toFixed(0) + "% source path"
                                                 : gaussianView.followPath
                                                   ? (gaussianView.pathProgress * 100).toFixed(0) + "% path"
                                                 : gaussianView.movementSpeed.toFixed(2) + " u/s")
                                        color: Theme.textSecondary
                                        font.family: Theme.monoFont
                                        font.pixelSize: 8
                                        horizontalAlignment: Text.AlignRight
                                    }
                                    Text {
                                        visible: false
                                        text: gaussianView.renderFps > 0
                                              ? gaussianView.renderFps.toFixed(0) + " render callbacks/s / "
                                                + gaussianView.geometryUpdateFps.toFixed(1) + " geometry Hz\n"
                                                + gaussianView.frameTimeMs.toFixed(1) + " ms CPU / "
                                                + (gaussianView.gpuTimeMs > 0
                                                   ? gaussianView.gpuTimeMs.toFixed(1) + " ms GPU / "
                                                   : "GPU n/a / ")
                                                + "same-frame geometry / lag "
                                                + gaussianView.cameraRevisionLag
                                              : "Ready\nVulkan"
                                        color: Theme.text
                                        font.family: Theme.monoFont
                                        font.pixelSize: 9
                                        horizontalAlignment: Text.AlignRight
                                    }
                                    IconButton {
                                        iconSource: Theme.icon("focus")
                                        toolTip: "Return to the first registered camera"
                                        buttonSize: 28
                                        onClicked: {
                                            gaussianView.resetCamera();
                                            root.recordedProgress = 0;
                                            gaussianView.forceActiveFocus();
                                        }
                                    }
                                }
                            }

                            Rectangle {
                                id: diagnosticPalette
                                z: 3
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 12
                                width: 132
                                height: 176
                                visible: root.exploreReady && !root.recordedCorridorMode
                                         && !root.driveMode
                                color: Theme.overlayHud
                                radius: Theme.cornerPopup

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    spacing: 4

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 5
                                        Text {
                                            text: "DIAGNOSTIC VIEW"
                                            color: Theme.textSecondary
                                            font.family: Theme.uiFont
                                            font.pixelSize: 8
                                            font.weight: Font.DemiBold
                                        }
                                        TextButton {
                                            compact: true
                                            text: "Appearance"
                                            selected: root.visualizationMode === 0
                                            toolTip: "RGB Gaussian appearance (key 1). This is not collision geometry."
                                            onClicked: {
                                                root.visualizationMode = 0;
                                                gaussianView.forceActiveFocus();
                                            }
                                        }
                                        TextButton {
                                            compact: true
                                            text: "Depth"
                                            selected: root.visualizationMode === 1
                                            toolTip: "Relative inferred depth heat map (key 2). It is not LiDAR or metric depth."
                                            onClicked: {
                                                root.visualizationMode = 1;
                                                gaussianView.forceActiveFocus();
                                            }
                                        }
                                        TextButton {
                                            compact: true
                                            text: "Structure"
                                            selected: root.visualizationMode === 2
                                            toolTip: "Splat shortest-axis structure cue (key 3). It is not a certified surface normal."
                                            onClicked: {
                                                root.visualizationMode = 2;
                                                gaussianView.forceActiveFocus();
                                            }
                                        }
                                        TextButton {
                                            compact: true
                                            text: "Coverage"
                                            selected: root.visualizationMode === 3
                                            toolTip: "Opacity support and gaps (key 4). Dark means weak or missing evidence."
                                            onClicked: {
                                                root.visualizationMode = 3;
                                                gaussianView.forceActiveFocus();
                                            }
                                        }
                                        Item {
                                            Layout.fillWidth: true
                                        }
                                        Rectangle {
                                            visible: false
                                            implicitWidth: 128
                                            implicitHeight: 22
                                            color: Theme.tintWarning
                                            radius: 8
                                            Text {
                                                anchors.centerIn: parent
                                                text: "NOT COLLISION READY"
                                                color: Theme.warning
                                                font.family: Theme.uiFont
                                                font.pixelSize: 8
                                                font.weight: Font.DemiBold
                                                font.letterSpacing: 0.5
                                            }
                                        }
                                    }
                                    Text {
                                        visible: false
                                        Layout.fillWidth: true
                                        text: root.visualizationDescription(root.visualizationMode)
                                        color: Theme.textMuted
                                        font.family: Theme.uiFont
                                        font.pixelSize: 8
                                        elide: Text.ElideRight
                                    }
                                }
                            }

                            Rectangle {
                                z: 2
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 12
                                anchors.verticalCenterOffset: 110
                                width: 132
                                height: 30
                                visible: root.exploreReady
                                         && root.hasSelection
                                         && String(root.selectedWorld.qualityTone) === "warning"
                                color: Theme.overlayWarn
                                radius: Theme.cornerPopup

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10
                                    spacing: 8
                                    SvgIcon {
                                        source: Theme.icon("warning")
                                        iconSize: Theme.iconXs
                                        color: Theme.warning
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "REVIEW REQUIRED"
                                        color: Theme.warning
                                        font.family: Theme.uiFont
                                        font.pixelSize: 8
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                    }
                                }
                            }

                            Rectangle {
                                z: 2
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.margins: 12
                                height: 52
                                visible: root.hasSelection && !root.exploreMode
                                color: Theme.overlayHud
                                radius: Theme.cornerPopup

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 11
                                    anchors.rightMargin: 11
                                    spacing: 9
                                    SvgIcon {
                                        source: Theme.icon("info")
                                        iconSize: Theme.iconMd
                                        color: Theme.info
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 1
                                        Text {
                                            text: "VALIDATION PREVIEW"
                                            color: Theme.textSecondary
                                            font.family: Theme.uiFont
                                            font.pixelSize: 8
                                            font.weight: Font.DemiBold
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: root.selectedWorldPublished
                                                  ? "The verified bundle is loaded. Choose Explore to enter the interactive Vulkan Gaussian world."
                                                  : "This run failed its quality gate. Its preview is diagnostic only; no Gaussian world was exported."
                                            color: Theme.textMuted
                                            font.family: Theme.uiFont
                                            font.pixelSize: 9
                                            elide: Text.ElideRight
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Panel {
                id: worldInspector
                visible: !Session.viewportFocusMode && root.detailsVisible
                SplitView.preferredWidth: 360
                SplitView.minimumWidth: 320
                SplitView.maximumWidth: 480

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "World details"
                        subtitle: root.hasSelection
                                  ? (root.selectedWorldPublished ? "Local bundle" : "Failed diagnostic")
                                  : "No selection"
                        iconSource: Theme.icon("inspector")
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
                                title: "Identity"
                                summary: root.hasSelection
                                         ? String(root.selectedWorld.displayName) : "—"

                                PropertyRow {
                                    label: "Name"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.displayName) : ""
                                        placeholderText: "No world"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Source"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.sourceSummary) : ""
                                        placeholderText: "Unavailable"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Created"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.createdText) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "World ID"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.worldId) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                            }

                            Section {
                                title: "Reconstruction"
                                summary: root.hasSelection
                                         ? String(root.selectedWorld.gaussianText) + " splats"
                                         : "—"

                                PropertyRow {
                                    label: "Profile"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.profileLabel) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Splats"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.gaussianText) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Type"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.representation) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Scale"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.scaleText) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                            }

                            Section {
                                title: "Quality"
                                summary: root.hasSelection
                                         ? String(root.selectedWorld.qualityLabel) : "—"

                                PropertyRow {
                                    label: "Tier"
                                    labelWidth: 82
                                    StatusBadge {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.qualityLabel) : "Unrated"
                                        tone: root.hasSelection
                                              ? String(root.selectedWorld.qualityTone) : "neutral"
                                    }
                                }
                                PropertyRow {
                                    label: "PSNR"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? root.metricText(root.selectedWorld.psnr, 2) + " dB"
                                              : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "SSIM"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? root.metricText(root.selectedWorld.ssim, 3) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                            }

                            Section {
                                title: "Storage"
                                summary: root.hasSelection
                                         ? String(root.selectedWorld.sizeText) : "—"

                                PropertyRow {
                                    label: "Job size"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.sizeText) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Location"
                                    labelWidth: 82
                                    TextButton {
                                        Layout.fillWidth: true
                                        text: "Open job folder"
                                        iconSource: Theme.icon("folder")
                                        enabled: root.hasSelection
                                        onClicked: WorldLibraryModel.openJobFolder(
                                                       String(root.selectedWorld.worldId))
                                    }
                                }
                            }

                            Section {
                                title: "Organize"

                                Item {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 44
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 12
                                        anchors.rightMargin: 12
                                        spacing: 7
                                        TextButton {
                                            Layout.fillWidth: true
                                            text: "Rename"
                                            iconSource: Theme.icon("edit")
                                            enabled: root.hasSelection && !WorldLibraryModel.busy
                                            onClicked: root.openRenameDialog()
                                        }
                                        TextButton {
                                            Layout.fillWidth: true
                                            text: "Delete"
                                            iconSource: Theme.icon("trash")
                                            tone: "danger"
                                            enabled: root.hasSelection && !WorldLibraryModel.busy
                                            onClicked: root.openDeleteDialog()
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Dialog {
        id: renameDialog

        property string worldId: ""

        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 420
        modal: true
        closePolicy: Popup.CloseOnEscape

        enter: Transition {
            NumberAnimation {
                property: "opacity"
                from: 0
                to: 1
                duration: Theme.animBase
                easing.type: Easing.OutCubic
            }
            NumberAnimation {
                property: "scale"
                from: 0.94
                to: 1
                duration: Theme.animSlow
                easing.type: Easing.OutCubic
            }
        }

        exit: Transition {
            NumberAnimation {
                property: "opacity"
                to: 0
                duration: Theme.animFast
                easing.type: Easing.InCubic
            }
        }

        background: Rectangle {
            color: Theme.panel
            border.width: 1
            border.color: Theme.borderStrong
            radius: Theme.cornerPopup
        }

        header: Rectangle {
            implicitHeight: 42
            color: Theme.chrome
            radius: Theme.cornerPopup
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 13
                anchors.verticalCenter: parent.verticalCenter
                text: "Rename world"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }
        }

        contentItem: ColumnLayout {
            spacing: 8
            Text {
                Layout.fillWidth: true
                text: "Use a clear local name. The verified world manifest and reconstruction files are not modified."
                color: Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }
            TextInput {
                id: renameField
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.controlHeight
                maximumLength: 80
                placeholderText: "World name"
                onAccepted: {
                    if (WorldLibraryModel.renameWorld(renameDialog.worldId, text))
                        renameDialog.close();
                }
            }
        }

        footer: Rectangle {
            implicitHeight: 48
            color: Theme.chrome
            radius: Theme.cornerPopup
            RowLayout {
                anchors.fill: parent
                anchors.margins: 9
                spacing: 7
                Item {
                    Layout.fillWidth: true
                }
                TextButton {
                    text: "Cancel"
                    onClicked: renameDialog.close()
                }
                TextButton {
                    text: "Save name"
                    tone: "primary"
                    enabled: renameField.text.trim().length > 0
                    onClicked: {
                        if (WorldLibraryModel.renameWorld(renameDialog.worldId,
                                                          renameField.text))
                            renameDialog.close();
                    }
                }
            }
        }
    }

    Dialog {
        id: deleteDialog

        property string worldId: ""
        property string worldName: ""
        property string storageText: ""

        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 460
        modal: true
        closePolicy: Popup.CloseOnEscape

        enter: Transition {
            NumberAnimation {
                property: "opacity"
                from: 0
                to: 1
                duration: Theme.animBase
                easing.type: Easing.OutCubic
            }
            NumberAnimation {
                property: "scale"
                from: 0.94
                to: 1
                duration: Theme.animSlow
                easing.type: Easing.OutCubic
            }
        }

        exit: Transition {
            NumberAnimation {
                property: "opacity"
                to: 0
                duration: Theme.animFast
                easing.type: Easing.InCubic
            }
        }

        background: Rectangle {
            color: Theme.panel
            border.width: 1
            border.color: Theme.borderStrong
            radius: Theme.cornerPopup
        }

        header: Rectangle {
            implicitHeight: 42
            color: Theme.tintError
            radius: Theme.cornerPopup
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 8
                SvgIcon {
                    source: Theme.icon("warning")
                    iconSize: Theme.iconMd
                    color: Theme.error
                }
                Text {
                    text: "Permanently delete world?"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }
        }

        contentItem: ColumnLayout {
            spacing: 10
            Text {
                Layout.fillWidth: true
                text: "Delete “" + deleteDialog.worldName + "” and recover approximately "
                      + deleteDialog.storageText + "?"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 11
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                text: "This removes the published bundle, extracted frames, camera solution, training checkpoints, validation renders, and logs for this job. This cannot be undone."
                color: Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.WordWrap
                lineHeight: 1.2
            }
        }

        footer: Rectangle {
            implicitHeight: 48
            color: Theme.chrome
            radius: Theme.cornerPopup
            RowLayout {
                anchors.fill: parent
                anchors.margins: 9
                spacing: 7
                Item {
                    Layout.fillWidth: true
                }
                TextButton {
                    text: "Cancel"
                    onClicked: deleteDialog.close()
                }
                TextButton {
                    text: "Delete permanently"
                    iconSource: Theme.icon("trash")
                    tone: "danger"
                    onClicked: {
                        if (WorldLibraryModel.deleteWorld(deleteDialog.worldId))
                            deleteDialog.close();
                    }
                }
            }
        }
    }
}
