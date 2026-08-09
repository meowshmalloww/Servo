pragma ComponentBehavior: Bound

import QtCore
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import "components"

ApplicationWindow {
    id: window

    width: 1440
    height: 860
    minimumWidth: 1040
    minimumHeight: 640
    visible: true
    title: Session.projectOpen ? "Servo - " + Session.projectName : "Servo"
    color: Theme.window

    readonly property var workspaceNames: ["Prepare", "Worlds", "Runs", "Diagnose", "Train", "Verify", "Capabilities"]
    readonly property var workspaceFiles: ["workspaces/PrepareWorkspace.qml", "workspaces/WorldsWorkspace.qml", "workspaces/RunsWorkspace.qml", "workspaces/DiagnoseWorkspace.qml", "workspaces/TrainWorkspace.qml", "workspaces/VerifyWorkspace.qml", "workspaces/CapabilitiesWorkspace.qml"]

    function showDebugTab(index) {
        debugDrawer.showTab(index);
    }

    palette.window: Theme.window
    palette.windowText: Theme.text
    palette.base: Theme.field
    palette.alternateBase: Theme.panelRaised
    palette.text: Theme.text
    palette.button: Theme.panelRaised
    palette.buttonText: Theme.text
    palette.highlight: Theme.selection
    palette.highlightedText: Theme.text
    palette.toolTipBase: Theme.panelRaised
    palette.toolTipText: Theme.text
    palette.placeholderText: Theme.textMuted

    Settings {
        id: appSettings
        category: "Workspace"
        property int selectedWorkspace: 1
        property bool showPerformanceMetrics: true
        property bool debugExpanded: false
        property int debugTab: 0
    }

    Component.onCompleted: {
        Session.workspaceIndex = Math.max(0, Math.min(6, appSettings.selectedWorkspace));
        Session.showPerformanceMetrics = appSettings.showPerformanceMetrics;
        workspaceSelector.currentIndex = Session.workspaceIndex;
        debugDrawer.currentTab = Math.max(0, Math.min(2, appSettings.debugTab));
        debugDrawer.expanded = appSettings.debugExpanded;
        RuntimeMetrics.attachWindow(window);
    }

    Connections {
        target: Session
        function onWorkspaceIndexChanged() {
            appSettings.selectedWorkspace = Session.workspaceIndex;
            workspaceSelector.currentIndex = Session.workspaceIndex;
            Session.viewportFocusMode = false;
        }
        function onShowPerformanceMetricsChanged() {
            appSettings.showPerformanceMetrics = Session.showPerformanceMetrics;
        }
        function onOpenProjectRequested() {
            projectDialog.open();
        }
        function onImportRecordingRequested() {
            recordingDialog.open();
        }
    }

    Connections {
        target: debugDrawer
        function onExpandedChanged() {
            appSettings.debugExpanded = debugDrawer.expanded;
        }
        function onCurrentTabChanged() {
            appSettings.debugTab = debugDrawer.currentTab;
        }
    }

    Shortcut {
        sequence: "Ctrl+O"
        onActivated: projectDialog.open()
    }
    Shortcut {
        sequence: "Ctrl+`"
        onActivated: {
            if (debugDrawer.expanded && debugDrawer.currentTab === 2)
                debugDrawer.expanded = false;
            else
                window.showDebugTab(2);
        }
    }
    Shortcut {
        sequence: "Ctrl+1"
        onActivated: Session.workspaceIndex = 0
    }
    Shortcut {
        sequence: "Ctrl+2"
        onActivated: Session.workspaceIndex = 1
    }
    Shortcut {
        sequence: "Ctrl+3"
        onActivated: Session.workspaceIndex = 2
    }
    Shortcut {
        sequence: "Ctrl+4"
        onActivated: Session.workspaceIndex = 3
    }
    Shortcut {
        sequence: "Ctrl+5"
        onActivated: Session.workspaceIndex = 4
    }
    Shortcut {
        sequence: "Ctrl+6"
        onActivated: Session.workspaceIndex = 5
    }
    Shortcut {
        sequence: "Ctrl+7"
        onActivated: Session.workspaceIndex = 6
    }

    menuBar: MenuBar {
        id: mainMenu
        height: Theme.menuHeight

        background: Rectangle {
            color: Theme.chrome
            border.width: 1
            border.color: Theme.borderSoft
        }

        delegate: MenuBarItem {
            id: menuItem
            implicitHeight: Theme.menuHeight
            leftPadding: 11
            rightPadding: 11

            contentItem: Text {
                text: menuItem.text
                color: menuItem.enabled ? Theme.textSecondary : Theme.textDisabled
                font.family: Theme.uiFont
                font.pixelSize: 10
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }

            background: Rectangle {
                color: menuItem.highlighted ? Theme.panelHover : "transparent"
                border.width: menuItem.highlighted ? 1 : 0
                border.color: Theme.borderStrong
            }
        }

        EditorMenu {
            title: "File"
            Action {
                text: "Open Project..."
                icon.source: Theme.icon("open")
                shortcut: "Ctrl+O"
                onTriggered: projectDialog.open()
            }
            Action {
                text: "Select Recording..."
                icon.source: Theme.icon("camera")
                enabled: Session.projectOpen
                onTriggered: recordingDialog.open()
            }
            EditorMenuSeparator {}
            Action {
                text: "Close Project"
                icon.source: Theme.icon("close")
                enabled: Session.projectOpen
                onTriggered: Session.closeProject()
            }
            EditorMenuSeparator {}
            Action {
                text: "Quit"
                shortcut: StandardKey.Quit
                onTriggered: window.close()
            }
        }

        EditorMenu {
            title: "View"

            Repeater {
                model: window.workspaceNames

                EditorMenuItem {
                    required property int index
                    required property string modelData
                    text: modelData
                    checkable: true
                    checked: Session.workspaceIndex === index
                    onTriggered: Session.workspaceIndex = index
                }
            }

            EditorMenuSeparator {}
            EditorMenuItem {
                text: "Focus Viewport"
                checkable: true
                checked: Session.viewportFocusMode
                enabled: Session.workspaceIndex === 1
                onTriggered: Session.viewportFocusMode = !Session.viewportFocusMode
            }
            EditorMenuItem {
                text: "Performance Readouts"
                checkable: true
                checked: Session.showPerformanceMetrics
                onTriggered: Session.showPerformanceMetrics = !Session.showPerformanceMetrics
            }
        }

        EditorMenu {
            title: "Window"
            Action {
                text: "Problems"
                icon.source: Theme.icon("warning")
                onTriggered: window.showDebugTab(0)
            }
            Action {
                text: "Output"
                icon.source: Theme.icon("table")
                onTriggered: window.showDebugTab(1)
            }
            Action {
                text: "Terminal"
                icon.source: Theme.icon("terminal")
                shortcut: "Ctrl+`"
                onTriggered: window.showDebugTab(2)
            }
            EditorMenuSeparator {}
            Action {
                text: "Reset Workspace Layout"
                icon.source: Theme.icon("refresh")
                onTriggered: Session.resetWorkspaceLayoutRequested()
            }
            Action {
                text: "Full Screen"
                shortcut: "F11"
                onTriggered: window.visibility = window.visibility === Window.FullScreen ? Window.Windowed : Window.FullScreen
            }
        }

        EditorMenu {
            title: "Help"
            Action {
                text: "About Servo"
                icon.source: Theme.icon("app")
                onTriggered: aboutDialog.open()
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.topBarHeight
            color: Theme.chrome
            border.width: 1
            border.color: Theme.borderSoft

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 9
                anchors.rightMargin: 7
                spacing: 7

                SvgIcon {
                    source: Theme.icon("app")
                    iconSize: 25
                }

                Text {
                    text: "SERVO"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 14
                    font.weight: Font.Bold
                    font.letterSpacing: 0.9
                }

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 22
                    color: Theme.border
                    Layout.leftMargin: 2
                    Layout.rightMargin: 2
                }

                SelectField {
                    id: workspaceSelector
                    Layout.preferredWidth: 142
                    Layout.preferredHeight: 28
                    Layout.fillWidth: false
                    model: window.workspaceNames
                    currentIndex: 1
                    onActivated: Session.workspaceIndex = currentIndex
                }

                SvgIcon {
                    source: Theme.icon("chevron-right")
                    iconSize: 11
                    opacity: 0.55
                }

                Text {
                    Layout.maximumWidth: 270
                    text: Session.projectOpen ? Session.projectName : "No project"
                    color: Session.projectOpen ? Theme.textSecondary : Theme.textMuted
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    elide: Text.ElideMiddle
                }

                TextButton {
                    visible: !Session.projectOpen
                    text: "Open Project"
                    iconSource: Theme.icon("open")
                    compact: true
                    onClicked: projectDialog.open()
                }

                Item {
                    Layout.fillWidth: true
                }

                RowLayout {
                    visible: Session.showPerformanceMetrics
                    spacing: 9

                    MetricReadout {
                        label: "FPS"
                        value: RuntimeMetrics.frameRateText
                        toolTip: "Measured window presentation activity. Idle means the event-driven UI is not continuously redrawing."
                    }
                    Rectangle {
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 16
                        color: Theme.borderSoft
                    }
                    MetricReadout {
                        label: "CPU"
                        value: RuntimeMetrics.cpuPercent < 0 ? "--" : Number(RuntimeMetrics.cpuPercent).toFixed(1) + "%"
                        toolTip: "Current Servo process CPU utilization"
                    }
                    Rectangle {
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 16
                        color: Theme.borderSoft
                    }
                    MetricReadout {
                        label: "RAM"
                        value: RuntimeMetrics.residentMemoryText
                        toolTip: "Current Servo process working set"
                    }
                    Rectangle {
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 16
                        color: Theme.borderSoft
                    }
                    MetricReadout {
                        label: "RHI"
                        value: RuntimeMetrics.graphicsApi
                        toolTip: "Graphics backend reported by the active Qt scene graph"
                    }
                }

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 22
                    color: Theme.border
                    Layout.leftMargin: 3
                }

                IconButton {
                    iconSource: Theme.icon("settings")
                    toolTip: "Settings"
                    buttonSize: 29
                    onClicked: settingsDialog.open()
                }
            }
        }

        Loader {
            id: workspaceLoader
            Layout.fillWidth: true
            Layout.fillHeight: true
            asynchronous: false
            source: window.workspaceFiles[Session.workspaceIndex]
        }

        BottomDrawer {
            id: debugDrawer
            Layout.fillWidth: true
            Layout.preferredHeight: implicitHeight
            tabs: ["Problems", "Output", "Terminal"]
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.statusHeight
            color: Theme.chrome
            border.width: 1
            border.color: Theme.borderSoft

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                spacing: 5

                SvgIcon {
                    source: Session.projectOpen ? Theme.icon("project") : Theme.icon("info")
                    iconSize: 12
                }

                Text {
                    text: Session.projectOpen ? Session.projectUrl.toString().replace("file:///", "") : "No project loaded"
                    color: Theme.textMuted
                    font.family: Theme.monoFont
                    font.pixelSize: 8
                    elide: Text.ElideMiddle
                    Layout.maximumWidth: 440
                }

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 12
                    color: Theme.borderSoft
                    Layout.leftMargin: 4
                    Layout.rightMargin: 4
                }

                TextButton {
                    text: "Problems"
                    compact: true
                    selected: debugDrawer.expanded && debugDrawer.currentTab === 0
                    onClicked: debugDrawer.expanded && debugDrawer.currentTab === 0 ? debugDrawer.expanded = false : window.showDebugTab(0)
                }
                TextButton {
                    text: "Output"
                    compact: true
                    selected: debugDrawer.expanded && debugDrawer.currentTab === 1
                    onClicked: debugDrawer.expanded && debugDrawer.currentTab === 1 ? debugDrawer.expanded = false : window.showDebugTab(1)
                }
                TextButton {
                    text: "Terminal"
                    compact: true
                    selected: debugDrawer.expanded && debugDrawer.currentTab === 2
                    onClicked: debugDrawer.expanded && debugDrawer.currentTab === 2 ? debugDrawer.expanded = false : window.showDebugTab(2)
                }

                Item {
                    Layout.fillWidth: true
                }

                Text {
                    text: RuntimeMetrics.sceneGraphReady ? "Renderer ready" : "Renderer initializing"
                    color: Theme.textMuted
                    font.family: Theme.uiFont
                    font.pixelSize: 8
                }

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 12
                    color: Theme.borderSoft
                }

                Text {
                    text: "Local frontend"
                    color: Theme.textMuted
                    font.family: Theme.uiFont
                    font.pixelSize: 8
                }
            }
        }
    }

    FileDialog {
        id: projectDialog
        title: "Open Servo Project"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Servo project (*.servo *.json)", "All files (*)"]
        onAccepted: Session.projectUrl = selectedFile
    }

    FileDialog {
        id: recordingDialog
        title: "Select Recording"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Sensor recordings (*.mp4 *.mov *.mcap *.bag)", "All files (*)"]
        onAccepted: Session.recordingUrl = selectedFile
    }

    SettingsDialog {
        id: settingsDialog
        anchors.centerIn: Overlay.overlay
    }

    Popup {
        id: aboutDialog
        width: 430
        height: 238
        anchors.centerIn: Overlay.overlay
        modal: true
        focus: true
        padding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            radius: Theme.cornerPopup
            color: Theme.panelRaised
            border.width: 1
            border.color: Theme.borderStrong
        }

        contentItem: ColumnLayout {
            spacing: 0

            PanelHeader {
                title: "About Servo"
                actionIcon: Theme.icon("close")
                actionToolTip: "Close"
                Layout.fillWidth: true
                onActionTriggered: aboutDialog.close()
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 18
                spacing: 14

                SvgIcon {
                    source: Theme.icon("app")
                    iconSize: 64
                    Layout.alignment: Qt.AlignTop
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 6

                    Text {
                        text: "SERVO"
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 20
                        font.weight: Font.Bold
                        font.letterSpacing: 1
                    }
                    Text {
                        text: "Simulation Environment for Robotic Validation and Optimization"
                        color: Theme.textSecondary
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    Text {
                        text: "Qt 6.11 / QML / C++20"
                        color: Theme.textMuted
                        font.family: Theme.monoFont
                        font.pixelSize: 9
                    }
                    Text {
                        text: "GPL-3.0-only"
                        color: Theme.textMuted
                        font.family: Theme.monoFont
                        font.pixelSize: 9
                    }
                    Item {
                        Layout.fillHeight: true
                    }
                    TextButton {
                        text: "Close"
                        Layout.alignment: Qt.AlignRight
                        onClicked: aboutDialog.close()
                    }
                }
            }
        }

        enter: Transition {}
        exit: Transition {}
    }
}
