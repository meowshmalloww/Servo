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
    visible: false
    title: Session.projectOpen ? "Servo - " + Session.projectName : "Servo"
    color: Theme.window

    readonly property var workspaceNames: ["Create World", "Worlds", "Runs", "Diagnose", "Train", "Verify", "Capabilities", "Assistant"]
    readonly property var workspaceFiles: ["workspaces/PrepareWorkspace.qml", "workspaces/WorldsWorkspace.qml", "workspaces/RunsWorkspace.qml", "workspaces/DiagnoseWorkspace.qml", "workspaces/TrainWorkspace.qml", "workspaces/VerifyWorkspace.qml", "workspaces/CapabilitiesWorkspace.qml", "workspaces/AiWorkspace.qml"]

    readonly property var workspaceIcons: ["build", "world", "run", "diagnose", "train", "verify", "capability", "assistant"]

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
        property int selectedWorkspace: 0
        property bool showPerformanceMetrics: true
        property bool debugExpanded: false
        property int debugTab: 0
        property bool darkTheme: true
        property bool motionEnabled: true
    }

    Component.onCompleted: {
        Theme.dark = appSettings.darkTheme;
        Theme.motionEnabled = appSettings.motionEnabled;
        Session.workspaceIndex = Math.max(0, Math.min(window.workspaceNames.length - 1, appSettings.selectedWorkspace));
        Session.showPerformanceMetrics = appSettings.showPerformanceMetrics;
        debugDrawer.currentTab = Math.max(0, Math.min(2, appSettings.debugTab));
        debugDrawer.expanded = appSettings.debugExpanded;
        Session.worldModel = WorldLibraryModel;
        RuntimeMetrics.attachWindow(window);
    }

    Connections {
        target: Theme
        function onDarkChanged() {
            appSettings.darkTheme = Theme.dark;
        }
        function onMotionEnabledChanged() {
            appSettings.motionEnabled = Theme.motionEnabled;
        }
    }

    function toggleTheme() {
        Theme.dark = !Theme.dark;
    }

    Connections {
        target: Session
        function onWorkspaceIndexChanged() {
            appSettings.selectedWorkspace = Session.workspaceIndex;
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

    Connections {
        target: ReconstructionController

        function onWorldPublished(worldPath) {
            WorldLibraryModel.selectWorldPath(worldPath);
            Session.worldModel = WorldLibraryModel;
            if (Session.workspaceIndex === 0)
                Session.workspaceIndex = 1;
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
    Shortcut {
        sequence: "Ctrl+8"
        onActivated: Session.workspaceIndex = 7
    }

    menuBar: MenuBar {
        id: mainMenu
        height: Theme.menuHeight

        background: Rectangle {
            color: Theme.chrome
        }

        delegate: MenuBarItem {
            id: menuItem
            implicitHeight: Theme.menuHeight
            leftPadding: 11
            rightPadding: 11

            contentItem: Text {
                text: menuItem.text
                color: menuItem.enabled ? (menuItem.highlighted ? Theme.accent : Theme.textSecondary) : Theme.textDisabled
                font.family: Theme.uiFont
                font.pixelSize: 10
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter

                Behavior on color {
                    ColorAnimation {
                        duration: Theme.animFast
                    }
                }
            }

            background: Rectangle {
                radius: Theme.cornerControl
                anchors.fill: parent
                anchors.margins: 3
                color: menuItem.highlighted ? Theme.panelHover : "transparent"

                Behavior on color {
                    ColorAnimation {
                        duration: Theme.animFast
                    }
                }
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
                icon.source: Theme.appLogo
                onTriggered: aboutDialog.open()
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            id: activityRail
            Layout.fillHeight: true
            Layout.preferredWidth: Theme.railWidth
            color: Theme.chrome

            ColumnLayout {
                anchors.fill: parent
                anchors.topMargin: 8
                spacing: 3

                Repeater {
                    model: window.workspaceNames

                    delegate: Item {
                        id: railItem
                        required property int index
                        required property string modelData

                        readonly property bool active: Session.workspaceIndex === railItem.index

                        Layout.fillWidth: true
                        Layout.preferredHeight: 40

                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: 5
                            radius: Theme.cornerCard - 2
                            color: railItem.active ? Theme.selection : (railHover.containsMouse ? Theme.panelRaised : "transparent")

                            Behavior on color {
                                ColorAnimation {
                                    duration: Theme.animFast
                                    easing.type: Easing.OutCubic
                                }
                            }
                        }

                        Rectangle {
                            anchors.left: parent.left
                            anchors.leftMargin: 2
                            anchors.verticalCenter: parent.verticalCenter
                            width: railItem.active ? 3 : 0
                            height: 16
                            radius: 1.5
                            color: Theme.accent

                            Behavior on width {
                                NumberAnimation {
                                    duration: Theme.animMove
                                    easing.type: Easing.OutCubic
                                }
                            }
                        }

                        SvgIcon {
                            anchors.centerIn: parent
                            source: Theme.icon(window.workspaceIcons[railItem.index])
                            iconSize: Theme.iconXl
                            color: railItem.active ? Theme.accent : (railHover.containsMouse ? Theme.text : Theme.textMuted)
                            scale: railHover.pressed ? 0.9 : 1.0

                            Behavior on color {
                                ColorAnimation {
                                    duration: Theme.animFast
                                }
                            }

                            Behavior on scale {
                                NumberAnimation {
                                    duration: Theme.animFast
                                    easing.type: Easing.OutCubic
                                }
                            }
                        }

                        MouseArea {
                            id: railHover
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Session.workspaceIndex = railItem.index
                        }

                        ToolTip {
                            visible: railHover.containsMouse
                            text: railItem.modelData + "  ·  Ctrl+" + (railItem.index + 1)
                            delay: 650
                        }
                    }
                }

                Item {
                    Layout.fillHeight: true
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Rectangle {
                id: topBar
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.topBarHeight
                color: Theme.chrome

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 7
                    spacing: 7

                    SvgIcon {
                        source: Theme.icon("app")
                        iconSize: 24
                        tinted: false
                    }

                    Text {
                        text: "SERVO"
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 13
                        font.weight: Font.Bold
                        font.letterSpacing: 0.9
                    }

                    Text {
                        Layout.leftMargin: 6
                        Layout.maximumWidth: 270
                        text: Session.projectOpen ? Session.projectName : "No project"
                        color: Session.projectOpen ? Theme.textSecondary : Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 11
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
                            value: RuntimeMetrics.presentationRateText
                            toolTip: "Frames actually presented by Servo. The active monitor can refresh at "
                                     + RuntimeMetrics.displayRefreshText
                                     + "; that refresh rate is a ceiling, not render performance."
                        }
                        MetricReadout {
                            label: "CPU"
                            value: RuntimeMetrics.cpuPercent < 0 ? "--" : Number(RuntimeMetrics.cpuPercent).toFixed(1) + "%"
                            toolTip: "Current Servo process CPU utilization"
                        }
                        MetricReadout {
                            label: "RAM"
                            value: RuntimeMetrics.residentMemoryText
                            toolTip: "Current Servo process working set"
                        }
                        MetricReadout {
                            label: "RHI"
                            value: RuntimeMetrics.graphicsApi
                            toolTip: RuntimeMetrics.graphicsDevice + " (" + RuntimeMetrics.graphicsDeviceType + ")"
                        }
                    }

                    IconButton {
                        iconSource: Theme.icon(Theme.dark ? "sun" : "moon")
                        toolTip: Theme.dark ? "Switch to light theme" : "Switch to dark theme"
                        buttonSize: 27
                        onClicked: window.toggleTheme()
                    }

                    IconButton {
                        iconSource: Theme.icon("settings")
                        toolTip: "Settings"
                        buttonSize: 27
                        rotation: settingsHover.hovered ? 45 : 0

                        Behavior on rotation {
                            NumberAnimation {
                                duration: Theme.animMove * 2
                                easing.type: Easing.OutCubic
                            }
                        }

                        HoverHandler {
                            id: settingsHover
                        }

                        onClicked: settingsDialog.open()
                    }
                }
            }

            Item {
                id: workspaceHost
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                Loader {
                    id: workspaceLoader
                    anchors.fill: parent
                    asynchronous: false
                    source: window.workspaceFiles[Session.workspaceIndex]

                    property real appear: 1

                    opacity: appear
                    transform: Translate {
                        y: (1 - workspaceLoader.appear) * 12
                    }

                    onSourceChanged: {
                        workspaceLoader.appear = 0;
                    }

                    onLoaded: {
                        appearAnimation.restart();
                    }

                    NumberAnimation {
                        id: appearAnimation
                        target: workspaceLoader
                        property: "appear"
                        from: 0
                        to: 1
                        duration: Theme.animSlow
                        easing.type: Easing.OutCubic
                    }
                }
            }

            BottomDrawer {
                id: debugDrawer
                Layout.fillWidth: true
                Layout.preferredHeight: implicitHeight
                tabs: ["Problems", "Output", "Terminal"]
            }

            Rectangle {
                id: statusBar
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.statusHeight
                color: Theme.chrome

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 6

                    SvgIcon {
                        source: Session.projectOpen ? Theme.icon("project") : Theme.icon("info")
                        iconSize: Theme.iconXs
                        color: Theme.textDisabled
                    }

                    Text {
                        text: Session.projectOpen ? Session.projectUrl.toString().replace("file:///", "") : "No project loaded"
                        color: Theme.textMuted
                        font.family: Theme.monoFont
                        font.pixelSize: 9
                        elide: Text.ElideMiddle
                        Layout.maximumWidth: 440
                    }

                    Item {
                        Layout.fillWidth: true
                    }

                    Text {
                        text: RuntimeMetrics.vulkanReady ? "Vulkan · " + RuntimeMetrics.graphicsDevice : "Vulkan initializing"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                    }

                    Text {
                        text: "Local frontend"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        Layout.leftMargin: 6
                    }
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
        parent: Overlay.overlay
        anchors.centerIn: parent
    }

    Popup {
        id: aboutDialog
        parent: Overlay.overlay
        popupType: Popup.Item
        width: Math.min(430, parent.width - 32)
        height: 238
        anchors.centerIn: parent
        modal: true
        focus: true
        padding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

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
                    source: Theme.appLogo
                    iconSize: 56
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
                        font.pixelSize: 19
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
                        tone: "primary"
                        Layout.alignment: Qt.AlignRight
                        onClicked: aboutDialog.close()
                    }
                }
            }
        }
    }
}
