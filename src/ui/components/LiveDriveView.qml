import QtQuick
import QtQuick.Layouts
import QtQuick3D
import QtQuick3D.AssetUtils
import "."

Item {
    id: root

    property var gaussianView: null
    property bool active: false
    property int cameraMode: 1
    property bool splitView: Qt.application.arguments.indexOf(
                                 "--native-drive-split-smoke") >= 0
    property real snowAccumulation: 0.0
    property url vehicleAssetSource: Qt.resolvedUrl("../assets/vehicles/OpenXVolvoEX30.glb")
    property string vehicleAssetName: "OpenX Volvo EX30 (2024)"
    readonly property bool vehicleOverlayDisabled: Qt.application.arguments.indexOf(
                                                       "--disable-native-vehicle-overlay") >= 0
    readonly property bool externalCamera: root.cameraMode !== 0

    focus: active

    function cameraLabel() {
        if (root.cameraMode === 0)
            return "FREE GAUSSIAN CAMERA";
        if (root.cameraMode === 1)
            return "CHASE - NATIVE VEHICLE";
        if (root.cameraMode === 2)
            return "DRIVER - NATIVE VEHICLE";
        if (root.cameraMode === 3)
            return "ORBIT - NATIVE VEHICLE";
        return "SIDE - NATIVE VEHICLE";
    }

    onCameraModeChanged: NativeVehicleController.cameraMode = root.cameraMode
    onSnowAccumulationChanged: NativeVehicleController.snowAccumulation = root.snowAccumulation
    Component.onCompleted: NativeVehicleController.snowAccumulation = root.snowAccumulation
    onSplitViewChanged: {
        if (splitView)
            root.cameraMode = 1;
    }
    onActiveChanged: {
        if (active)
            forceActiveFocus();
        else
            NativeVehicleController.clearInputs();
    }

    Binding {
        target: root.gaussianView
        property: "externalCameraEnabled"
        value: root.active && NativeVehicleController.running && root.externalCamera
        when: root.gaussianView !== null
    }
    Binding {
        target: root.gaussianView
        property: "simulationCameraMode"
        value: root.externalCamera ? root.cameraMode : 0
        when: root.gaussianView !== null
    }
    Binding {
        target: root.gaussianView
        property: "externalCameraPosition"
        value: NativeVehicleController.cameraPosition
        when: root.gaussianView !== null
    }
    Binding {
        target: root.gaussianView
        property: "externalCameraOrientation"
        value: NativeVehicleController.cameraOrientation
        when: root.gaussianView !== null
    }
    Binding {
        target: root.gaussianView
        property: "egoVehiclePosition"
        value: NativeVehicleController.vehiclePosition
        when: root.gaussianView !== null
    }
    Binding {
        target: root.gaussianView
        property: "egoVehicleOrientation"
        value: NativeVehicleController.vehicleOrientation
        when: root.gaussianView !== null
    }
    Binding {
        target: root.gaussianView
        property: "simulationFrameId"
        value: NativeVehicleController.frameId
        when: root.gaussianView !== null
    }

    GaussianSplatView {
        id: driverGaussianView
        z: 0
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.bottom: controls.top
        width: Math.floor(parent.width / 2)
        visible: root.active && root.splitView
        source: visible && root.gaussianView !== null ? root.gaussianView.source : ""
        visualizationMode: root.gaussianView !== null ? root.gaussianView.visualizationMode : 0
        externalCameraEnabled: visible
        externalCameraPosition: NativeVehicleController.driverCameraPosition
        externalCameraOrientation: NativeVehicleController.driverCameraOrientation
        externalVerticalFieldOfView: root.gaussianView !== null
                                     ? root.gaussianView.externalVerticalFieldOfView : 52
        simulationCameraMode: 2
        egoVehiclePosition: NativeVehicleController.vehiclePosition
        egoVehicleOrientation: NativeVehicleController.vehicleOrientation
        simulationFrameId: NativeVehicleController.frameId
        snowAccumulation: root.snowAccumulation
    }

    // The Gaussian scene remains the background rendered by GaussianSplatView.
    // This transparent Quick 3D pass draws a complete glTF vehicle from the
    // same camera pose; it is not a CARLA image or prerecorded sprite.
    View3D {
        id: vehiclePass
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        width: root.splitView ? Math.floor(parent.width / 2) : parent.width
        // Inline rendering preserves the already-rendered Gaussian world.
        // The default Offscreen path produced an opaque black compositing
        // surface on the Vulkan/QQuickRhiItem combination used by Servo.
        renderMode: View3D.Inline
        visible: root.active && !root.vehicleOverlayDisabled
                 && root.externalCamera && root.cameraMode !== 2
                 && NativeVehicleController.ready
        camera: vehicleCamera

        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
            tonemapMode: SceneEnvironment.TonemapModeAces
        }

        PerspectiveCamera {
            id: vehicleCamera
            position: NativeVehicleController.overlayCameraPosition
            rotation: NativeVehicleController.overlayCameraOrientation
            clipNear: 8
            clipFar: 2500
            fieldOfView: root.gaussianView !== null
                         ? root.gaussianView.externalVerticalFieldOfView : 52
        }

        DirectionalLight {
            eulerRotation.x: -42
            eulerRotation.y: -28
            brightness: 0.62
            castsShadow: true
            shadowFactor: 78
            shadowMapQuality: Light.ShadowMapQualityHigh
        }
        DirectionalLight {
            eulerRotation.x: 28
            eulerRotation.y: 145
            brightness: 0.16
        }
        DirectionalLight {
            rotation: vehicleCamera.rotation
            brightness: 0.72
        }

        Node {
            id: vehicleRoot
            position: Qt.vector3d(0,
                                  -NativeVehicleController.bodyClearanceMeters * 100,
                                  0)
            // OpenX authors vehicle forward along +X. Servo physics uses +Z.
            eulerRotation: Qt.vector3d(0, -90, 0)

            RuntimeLoader {
                id: carModel
                source: root.vehicleAssetSource
                scale: Qt.vector3d(100, 100, 100)
            }

            PrincipledMaterial {
                id: accumulatedSnowMaterial
                baseColor: Qt.rgba(0.91, 0.94, 0.97,
                                   0.96 * root.snowAccumulation)
                roughness: 0.93
                metalness: 0.0
                alphaMode: PrincipledMaterial.Blend
            }

            // Persistent top-surface deposits move with the physical vehicle.
            // These are geometry, not a screen-space particle/image overlay.
            Model {
                source: "#Sphere"
                visible: root.snowAccumulation > 0.01
                position: Qt.vector3d(-18, 160 + 3.0 * root.snowAccumulation, 0)
                scale: Qt.vector3d(1.25,
                                   0.020 + 0.050 * root.snowAccumulation,
                                   0.76)
                materials: [accumulatedSnowMaterial]
            }
            Model {
                source: "#Sphere"
                visible: root.snowAccumulation > 0.01
                position: Qt.vector3d(135, 119 + 2.2 * root.snowAccumulation, 0)
                eulerRotation.z: -7
                scale: Qt.vector3d(0.82,
                                   0.014 + 0.038 * root.snowAccumulation,
                                   0.80)
                materials: [accumulatedSnowMaterial]
            }
            Model {
                source: "#Sphere"
                visible: root.snowAccumulation > 0.01
                position: Qt.vector3d(-154, 115 + 2.0 * root.snowAccumulation, 0)
                eulerRotation.z: 13
                scale: Qt.vector3d(0.48,
                                   0.012 + 0.032 * root.snowAccumulation,
                                   0.74)
                materials: [accumulatedSnowMaterial]
            }
        }
    }

    Rectangle {
        z: 4
        anchors.top: parent.top
        anchors.bottom: controls.top
        anchors.horizontalCenter: parent.horizontalCenter
        width: 1
        color: Theme.borderStrong
        visible: root.splitView
    }

    Rectangle {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 34
        color: Theme.overlayHud
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            spacing: 8
            StatusBadge { text: root.cameraLabel(); tone: "success" }
            TextButton {
                compact: true
                text: root.splitView ? "Single view" : "Split cameras"
                selected: root.splitView
                toolTip: "Toggle synchronized Chase and Driver Gaussian views. Shortcut: 6"
                onClicked: {
                    root.splitView = !root.splitView;
                    root.forceActiveFocus();
                }
            }
            TextButton {
                compact: true
                text: Session.worldWeather === "snow" ? "Clear weather" : "Snow"
                selected: Session.worldWeather === "snow"
                toolTip: "Toggle persistent inferred-surface snow accumulation and snow tyre grip"
                onClicked: {
                    Session.worldWeather = Session.worldWeather === "snow" ? "clear" : "snow";
                    root.forceActiveFocus();
                }
            }
            StatusBadge {
                text: NativeVehicleController.autoDriveEnabled
                      ? "AUTO DRIVE" : "MANUAL DRIVE"
                tone: "info"
            }
            StatusBadge { visible: root.width >= 1250; text: "PHYSICS - 9.81 m/s2"; tone: "success" }
            StatusBadge { visible: root.width >= 1250; text: "ROAD - WORLD DESCRIPTOR"; tone: "warning" }
            StatusBadge {
                visible: root.snowAccumulation > 0.01
                text: "SNOW " + Math.round(root.snowAccumulation * 100)
                      + "% - GRIP " + NativeVehicleController.effectiveTyreFriction.toFixed(2)
                tone: "warning"
            }
            StatusBadge { visible: root.width >= 1450; text: root.vehicleAssetName.toUpperCase() + " - COMPLETE 3D"; tone: "info" }
            Item { Layout.fillWidth: true }
            StatusBadge {
                text: NativeVehicleController.status
                tone: NativeVehicleController.falling ? "error"
                      : NativeVehicleController.grounded ? "success" : "warning"
            }
        }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(470, parent.width - 40)
        height: nativeError.implicitHeight + 42
        radius: Theme.cornerPopup
        color: Theme.overlayHud
        visible: root.active && !NativeVehicleController.ready
        Text {
            id: nativeError
            anchors.centerIn: parent
            width: parent.width - 28
            text: NativeVehicleController.errorString.length > 0
                  ? NativeVehicleController.errorString
                  : "This Gaussian world has no native road-physics binding."
            color: Theme.error
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            font.family: Theme.uiFont
            font.pixelSize: 11
        }
    }

    MouseArea {
        property real previousX: 0
        property real previousY: 0
        anchors.fill: parent
        anchors.topMargin: 34
        anchors.bottomMargin: 48
        enabled: root.active && root.externalCamera
        acceptedButtons: Qt.LeftButton
        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
        onPressed: mouse => {
            previousX = mouse.x;
            previousY = mouse.y;
            root.forceActiveFocus();
        }
        onPositionChanged: mouse => {
            if (!pressed || root.cameraMode !== 3)
                return;
            NativeVehicleController.orbitCamera((mouse.x - previousX) * 0.22,
                                                -(mouse.y - previousY) * 0.18);
            previousX = mouse.x;
            previousY = mouse.y;
        }
    }

    Keys.onPressed: event => {
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
        else if (event.key >= Qt.Key_1 && event.key <= Qt.Key_5)
            root.cameraMode = event.key - Qt.Key_1;
        else if (event.key === Qt.Key_6)
            root.splitView = !root.splitView;
        else
            return;
        event.accepted = true;
    }
    Keys.onReleased: event => {
        if (event.isAutoRepeat)
            return;
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
    }

    DrivingHud {
        anchors.left: parent.left
        anchors.bottom: controls.top
        anchors.leftMargin: 12
        anchors.bottomMargin: 8
        visible: root.active
    }

    Rectangle {
        id: controls
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 46
        color: Theme.overlayHud
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            spacing: 6
            TextButton { compact: true; text: "Free"; selected: root.cameraMode === 0; onClicked: { root.cameraMode = 0; root.forceActiveFocus(); } }
            TextButton { compact: true; text: "Chase"; selected: root.cameraMode === 1; onClicked: { root.cameraMode = 1; root.forceActiveFocus(); } }
            TextButton { compact: true; text: "Driver"; selected: root.cameraMode === 2; onClicked: { root.cameraMode = 2; root.forceActiveFocus(); } }
            TextButton { compact: true; text: "Orbit"; selected: root.cameraMode === 3; onClicked: { root.cameraMode = 3; root.forceActiveFocus(); } }
            TextButton { compact: true; text: "Side"; selected: root.cameraMode === 4; onClicked: { root.cameraMode = 4; root.forceActiveFocus(); } }
            TextButton {
                compact: true
                text: "Split"
                selected: root.splitView
                toolTip: "Render synchronized Chase and Driver Gaussian cameras side by side. This performs a second live Gaussian pass and is optional."
                onClicked: {
                    root.splitView = !root.splitView;
                    root.forceActiveFocus();
                }
            }
            TextButton {
                compact: true
                text: "Auto route"
                selected: NativeVehicleController.autoDriveEnabled
                toolTip: "Follow the finite road descriptor published by the selected world. No prerecorded steering or map-specific coordinates."
                onClicked: {
                    NativeVehicleController.autoDriveEnabled = !NativeVehicleController.autoDriveEnabled;
                    root.forceActiveFocus();
                }
            }
            Text { text: "W/S throttle - A/D steer - Space brake - R reset"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9 }
            Item { Layout.fillWidth: true }
            TextButton { compact: true; text: "Drop test"; toolTip: "Place the car eight metres above the reconstructed road and let gravity act."; onClicked: { NativeVehicleController.dropFromHeight(8); root.forceActiveFocus(); } }
            TextButton { compact: true; text: "Pause"; enabled: NativeVehicleController.running && !NativeVehicleController.paused; onClicked: NativeVehicleController.pause() }
            TextButton { compact: true; text: "Resume"; enabled: NativeVehicleController.running && NativeVehicleController.paused; onClicked: { NativeVehicleController.resume(); root.forceActiveFocus(); } }
            TextButton { compact: true; text: "Stop"; tone: "danger"; enabled: NativeVehicleController.running; onClicked: NativeVehicleController.stop() }
        }
    }
}
