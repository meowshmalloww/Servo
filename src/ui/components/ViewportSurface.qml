pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick3D
import QtQuick3D.Helpers
import "."

Panel {
    id: root

    property string title: "World View"
    property string emptyTitle: "No world loaded"
    property string emptyDescription: "Open or compile a world to attach render content."
    property bool available: false
    property bool gridVisible: true
    property bool statsVisible: false
    property int toolMode: 1
    property int cameraPreset: 0

    function resetCamera() {
        cameraRig.position = Qt.vector3d(0, 0, 0);
        cameraRig.eulerRotation = Qt.vector3d(-32, -38, 0);
        editorCamera.position = Qt.vector3d(0, 0, 720);
        cameraPreset = 0;
        cameraPresetField.currentIndex = 0;
    }

    function applyCameraPreset(index) {
        cameraPreset = index;
        cameraRig.position = Qt.vector3d(0, 0, 0);
        editorCamera.position = Qt.vector3d(0, 0, index === 0 ? 720 : 850);

        if (index === 1)
            cameraRig.eulerRotation = Qt.vector3d(-90, 0, 0);
        else if (index === 2)
            cameraRig.eulerRotation = Qt.vector3d(0, 0, 0);
        else if (index === 3)
            cameraRig.eulerRotation = Qt.vector3d(0, 90, 0);
        else
            cameraRig.eulerRotation = Qt.vector3d(-32, -38, 0);
    }

    color: Theme.viewport

    onStatsVisibleChanged: worldView.renderStats.extendedDataCollectionEnabled = statsVisible

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 34
            color: Theme.chrome
            border.width: 1
            border.color: Theme.borderSoft

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 6
                anchors.rightMargin: 5
                spacing: 3

                IconButton {
                    iconSource: Theme.icon("select")
                    toolTip: "Select tool"
                    selected: root.toolMode === 0
                    buttonSize: 25
                    onClicked: root.toolMode = 0
                }

                IconButton {
                    iconSource: Theme.icon("orbit")
                    toolTip: "Orbit camera - drag to orbit, Ctrl+drag to pan, wheel to zoom"
                    selected: root.toolMode === 1
                    buttonSize: 25
                    onClicked: root.toolMode = 1
                }

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 18
                    color: Theme.border
                    Layout.leftMargin: 3
                    Layout.rightMargin: 3
                }

                SelectField {
                    id: cameraPresetField
                    Layout.preferredWidth: 126
                    Layout.preferredHeight: 25
                    Layout.fillWidth: false
                    model: ["Perspective", "Top", "Front", "Right"]
                    currentIndex: 0
                    onActivated: root.applyCameraPreset(currentIndex)
                }

                IconButton {
                    iconSource: Theme.icon("focus")
                    toolTip: "Reset camera"
                    buttonSize: 25
                    onClicked: root.resetCamera()
                }

                Item {
                    Layout.fillWidth: true
                }

                Text {
                    text: root.title
                    color: Theme.textMuted
                    font.family: Theme.uiFont
                    font.pixelSize: 9
                    elide: Text.ElideRight
                    Layout.maximumWidth: 180
                }

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 18
                    color: Theme.border
                    Layout.leftMargin: 4
                    Layout.rightMargin: 4
                }

                IconButton {
                    iconSource: Theme.icon("grid")
                    toolTip: root.gridVisible ? "Hide editor grid" : "Show editor grid"
                    selected: root.gridVisible
                    buttonSize: 25
                    onClicked: root.gridVisible = !root.gridVisible
                }

                IconButton {
                    iconSource: Theme.icon("chart")
                    toolTip: root.statsVisible ? "Hide render statistics" : "Show render statistics"
                    selected: root.statsVisible
                    buttonSize: 25
                    onClicked: root.statsVisible = !root.statsVisible
                }

                IconButton {
                    iconSource: Theme.icon(Session.viewportFocusMode ? "minimize" : "maximize")
                    toolTip: Session.viewportFocusMode ? "Restore editor panels" : "Focus viewport"
                    selected: Session.viewportFocusMode
                    buttonSize: 25
                    onClicked: Session.viewportFocusMode = !Session.viewportFocusMode
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            View3D {
                id: worldView
                anchors.fill: parent
                renderMode: View3D.Offscreen

                environment: SceneEnvironment {
                    clearColor: Theme.viewport
                    backgroundMode: SceneEnvironment.Color
                    antialiasingMode: SceneEnvironment.MSAA
                    antialiasingQuality: SceneEnvironment.Medium

                    InfiniteGrid {
                        visible: root.gridVisible
                        gridInterval: 100
                        gridAxes: false
                    }
                }

                camera: editorCamera

                Node {
                    id: cameraRig
                    eulerRotation: Qt.vector3d(-32, -38, 0)

                    PerspectiveCamera {
                        id: editorCamera
                        z: 720
                        clipNear: 0.5
                        clipFar: 250000
                        fieldOfView: 52
                    }
                }

                DirectionalLight {
                    eulerRotation: Qt.vector3d(-45, -35, 0)
                    brightness: 0.7
                    ambientColor: "#2b2e30"
                    castsShadow: false
                }
            }

            OrbitCameraController {
                anchors.fill: parent
                origin: cameraRig
                camera: editorCamera
                mouseEnabled: root.toolMode === 1
                panEnabled: true
                automaticClipping: true
                acceptedButtons: Qt.LeftButton | Qt.MiddleButton
            }

            Rectangle {
                anchors.centerIn: parent
                width: Math.min(430, parent.width - 48)
                height: 112
                visible: !root.available
                color: "#d817191b"
                border.width: 1
                border.color: Theme.border
                radius: Theme.cornerPopup

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 5

                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter
                        spacing: 8
                        SvgIcon {
                            source: Theme.icon("world")
                            iconSize: 17
                        }
                        Text {
                            text: root.emptyTitle
                            color: Theme.text
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.emptyDescription
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "The viewport is live. Drag to orbit, Ctrl+drag to pan, and use the wheel to zoom."
                        color: Theme.textDisabled
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        horizontalAlignment: Text.AlignHCenter
                    }
                }
            }

            Rectangle {
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.topMargin: 10
                anchors.rightMargin: 10
                width: 190
                height: 116
                visible: root.statsVisible
                color: "#e5191c1e"
                border.width: 1
                border.color: Theme.borderStrong
                radius: Theme.cornerControl

                GridLayout {
                    anchors.fill: parent
                    anchors.margins: 9
                    columns: 2
                    rowSpacing: 5
                    columnSpacing: 12

                    Text {
                        text: "Scene activity"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                    }
                    Text {
                        text: worldView.renderStats.fps > 2
                              ? Math.round(worldView.renderStats.fps) + " fps" : "Idle"
                        color: Theme.text
                        font.family: Theme.monoFont
                        font.pixelSize: 9
                        Layout.alignment: Qt.AlignRight
                    }
                    Text {
                        text: "Display"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                    }
                    Text {
                        text: RuntimeMetrics.displayRefreshText
                        color: Theme.text
                        font.family: Theme.monoFont
                        font.pixelSize: 9
                        Layout.alignment: Qt.AlignRight
                    }
                    Text {
                        text: "Frame"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                    }
                    Text {
                        text: Number(worldView.renderStats.frameTime).toFixed(2) + " ms"
                        color: Theme.text
                        font.family: Theme.monoFont
                        font.pixelSize: 9
                        Layout.alignment: Qt.AlignRight
                    }
                    Text {
                        text: "Draw calls"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                    }
                    Text {
                        text: worldView.renderStats.drawCallCount
                        color: Theme.text
                        font.family: Theme.monoFont
                        font.pixelSize: 9
                        Layout.alignment: Qt.AlignRight
                    }
                    Text {
                        text: "GPU memory"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                    }
                    Text {
                        text: worldView.renderStats.vmemUsedBytes > 0 ? Math.round(worldView.renderStats.vmemUsedBytes / 1048576) + " MB" : "--"
                        color: Theme.text
                        font.family: Theme.monoFont
                        font.pixelSize: 9
                        Layout.alignment: Qt.AlignRight
                    }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 24
                color: "#e5191c1e"
                border.width: 1
                border.color: Theme.borderSoft

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    spacing: 8

                    Text {
                        text: cameraPresetField.displayText
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                    }
                    Rectangle {
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 11
                        color: Theme.border
                    }
                    Text {
                        text: root.gridVisible ? "Grid 1 m" : "Grid hidden"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    Text {
                        text: worldView.renderStats.graphicsApiName
                        color: Theme.textMuted
                        font.family: Theme.monoFont
                        font.pixelSize: 8
                    }
                    Rectangle {
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 11
                        color: Theme.border
                    }
                    Text {
                        text: root.available ? "World attached" : "No world source"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                    }
                }
            }
        }
    }
}
