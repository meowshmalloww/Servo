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

    // Keep primary navigation task-shaped. The disconnected diagnostic,
    // training, verification, and capability shells remain available to the
    // backend workbench, but no longer compete with the hackathon flow.
    readonly property var workspaceNames: ["Create", "Worlds", "Runs", "Assistant", "Settings"]
    readonly property var workspaceFiles: ["workspaces/PrepareWorkspace.qml", "workspaces/WorldsWorkspace.qml", "workspaces/RunsWorkspace.qml", "workspaces/AiWorkspace.qml", "workspaces/SettingsWorkspace.qml"]

    readonly property var workspaceIcons: ["build", "world", "run", "assistant", "settings"]

    function showDebugTab(index) {
        debugDrawer.showTab(index);
    }

    function applyControlPlaneAuthentication() {
        RealityCIController.setBearerToken(AuthController.accessToken);
        SimulationController.setBearerToken(AuthController.accessToken);
        if (AuthController.authenticated) {
            RealityCIController.connectToServer();
            SimulationController.connectToServer();
        }
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
        window.applyControlPlaneAuthentication();
    }

    Connections {
        target: AuthController
        function onAccessTokenChanged() {
            window.applyControlPlaneAuthentication();
        }
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

    Connections {
        target: AiChatController
        function onActionRequested(action, argument) {
            if (action === "create-world")
                Session.workspaceIndex = 0;
            else if (action === "open-worlds" || action === "explore-world")
                Session.workspaceIndex = 1;
            else if (action === "open-runs")
                Session.workspaceIndex = 2;
            if (action === "weather")
                Session.worldWeather = argument === "snow" ? "snow" : "clear";
            Session.assistantActionRequested(action, argument);
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
        sequence: "Ctrl+,"
        onActivated: Session.workspaceIndex = 4
    }

    menuBar: MenuBar {
        id: mainMenu
        visible: AuthController.authenticated
        height: Theme.menuHeight

        background: Rectangle {
            color: Theme.chrome

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: Theme.borderSoft
                opacity: 0.5
            }
        }

        delegate: MenuBarItem {
            id: menuItem
            implicitHeight: Theme.menuHeight
            leftPadding: 10
            rightPadding: 10

            contentItem: Text {
                text: menuItem.text
                color: menuItem.enabled ? (menuItem.highlighted ? Theme.text : Theme.textSecondary) : Theme.textDisabled
                font.family: Theme.uiFont
                font.pixelSize: 11
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter

                Behavior on color {
                    enabled: Theme.motionEnabled
                    ColorAnimation { duration: Theme.animFast; easing.type: Easing.OutCubic }
                }
            }

            background: Rectangle {
                radius: Theme.cornerControl
                anchors.fill: parent
                anchors.margins: 3
                color: menuItem.highlighted ? Theme.panelHover : "transparent"
                opacity: menuItem.highlighted ? 1 : 0

                Behavior on opacity {
                    enabled: Theme.motionEnabled
                    NumberAnimation { duration: Theme.animFast; easing.type: Easing.OutCubic }
                }
                Behavior on color {
                    enabled: Theme.motionEnabled
                    ColorAnimation { duration: Theme.animFast; easing.type: Easing.OutCubic }
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
        visible: AuthController.authenticated
        enabled: AuthController.authenticated
        spacing: 0

        Rectangle {
            id: activityRail
            Layout.fillHeight: true
            Layout.preferredWidth: Theme.railWidth
            color: Theme.chrome

            Rectangle {
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                width: 1
                color: Theme.borderSoft
                opacity: 0.55
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.topMargin: 10
                anchors.bottomMargin: 10
                spacing: 2

                Repeater {
                    model: window.workspaceNames

                    delegate: Item {
                        id: railItem
                        required property int index
                        required property string modelData

                        readonly property bool active: Session.workspaceIndex === railItem.index
                        readonly property bool hovered: railHover.containsMouse

                        Layout.fillWidth: true
                        Layout.preferredHeight: 46

                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: 4
                            radius: 8
                            color: railItem.active ? Theme.selection : (railItem.hovered ? Theme.panelHover : "transparent")
                            border.width: railItem.active ? 1 : 0
                            border.color: Theme.borderSoft
                            opacity: railItem.active ? 1 : (railItem.hovered ? 0.85 : 0)

                            Behavior on opacity {
                                enabled: Theme.motionEnabled
                                NumberAnimation { duration: Theme.animFast; easing.type: Easing.OutCubic }
                            }
                            Behavior on color {
                                enabled: Theme.motionEnabled
                                ColorAnimation { duration: Theme.animFast; easing.type: Easing.OutCubic }
                            }
                        }

                        Rectangle {
                            anchors.left: parent.left
                            anchors.leftMargin: 2
                            anchors.verticalCenter: parent.verticalCenter
                            width: 3
                            height: railItem.active ? 20 : 0
                            radius: 1.5
                            color: Theme.accent
                            opacity: railItem.active ? 1 : 0

                            Behavior on height {
                                enabled: Theme.motionEnabled
                                NumberAnimation { duration: Theme.animMove; easing.type: Easing.OutCubic }
                            }
                            Behavior on opacity {
                                enabled: Theme.motionEnabled
                                NumberAnimation { duration: Theme.animFast; easing.type: Easing.OutCubic }
                            }
                        }

                        SvgIcon {
                            anchors.centerIn: parent
                            source: Theme.icon(window.workspaceIcons[railItem.index])
                            iconSize: Theme.iconXl
                            color: railItem.active ? Theme.text : (railItem.hovered ? Theme.text : Theme.textMuted)

                            Behavior on color {
                                enabled: Theme.motionEnabled
                                ColorAnimation { duration: Theme.animFast; easing.type: Easing.OutCubic }
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
                    Layout.minimumHeight: 12
                }

                Rectangle {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: 22
                    Layout.preferredHeight: 1
                    color: Theme.borderSoft
                    opacity: 0.6
                    Layout.bottomMargin: 6
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

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: Theme.borderSoft
                    opacity: 0.55
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 8
                    spacing: 8

                    Image {
                        Layout.preferredWidth: 22
                        Layout.preferredHeight: 22
                        source: Theme.appLogo
                        sourceSize: Qt.size(44, 44)
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        mipmap: true
                        Layout.alignment: Qt.AlignVCenter
                    }

                    Text {
                        text: "SERVO"
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        font.letterSpacing: 0.7
                        Layout.alignment: Qt.AlignVCenter
                    }

                    Rectangle {
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 16
                        Layout.leftMargin: 4
                        Layout.rightMargin: 2
                        color: Theme.borderSoft
                        opacity: 0.7
                        Layout.alignment: Qt.AlignVCenter
                    }

                    Text {
                        Layout.maximumWidth: Math.min(260, Math.max(120, topBar.width - 560))
                        text: Session.projectOpen ? Session.projectName : "No project"
                        color: Session.projectOpen ? Theme.textSecondary : Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                        elide: Text.ElideMiddle
                        Layout.alignment: Qt.AlignVCenter
                    }

                    TextButton {
                        visible: !Session.projectOpen
                        text: "Open Project"
                        iconSource: Theme.icon("open")
                        compact: true
                        Layout.alignment: Qt.AlignVCenter
                        onClicked: projectDialog.open()
                    }

                    Item {
                        Layout.fillWidth: true
                    }

                    TextButton {
                        text: "Ask Servo"
                        iconSource: Theme.icon("assistant")
                        selected: Session.workspaceIndex === 3
                        compact: true
                        Layout.alignment: Qt.AlignVCenter
                        onClicked: Session.workspaceIndex = 3
                    }

                    TextButton {
                        visible: !AuthController.localMode
                        text: "Sign out"
                        toolTip: AuthController.email.length > 0
                                 ? "Signed in as " + AuthController.email
                                 : "End Firebase session"
                        compact: true
                        Layout.alignment: Qt.AlignVCenter
                        onClicked: AuthController.signOut()
                    }

                    RowLayout {
                        id: perfRow
                        spacing: 10
                        Layout.alignment: Qt.AlignVCenter
                        visible: Session.showPerformanceMetrics
                        opacity: window.width >= 1200 ? 1 : (window.width >= 1060 ? 0.9 : 0)

                        Behavior on opacity {
                            enabled: Theme.motionEnabled
                            NumberAnimation { duration: Theme.animFast; easing.type: Easing.OutCubic }
                        }

                        MetricReadout {
                            label: "FPS"
                            value: RuntimeMetrics.presentationRateText
                            toolTip: "Frames actually presented by Servo. The active monitor can refresh at "
                                     + RuntimeMetrics.displayRefreshText
                                     + "; that refresh rate is a ceiling, not render performance."
                            opacity: window.width >= 980 ? 1 : 0
                            visible: opacity > 0
                            Behavior on opacity { NumberAnimation { duration: Theme.animFast } }
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
                            opacity: window.width >= 1120 ? 1 : 0
                            visible: opacity > 0
                            Behavior on opacity { NumberAnimation { duration: Theme.animFast } }
                        }
                        MetricReadout {
                            label: "RHI"
                            value: RuntimeMetrics.graphicsApi
                            toolTip: RuntimeMetrics.graphicsDevice + " (" + RuntimeMetrics.graphicsDeviceType + ")"
                            opacity: window.width >= 1200 ? 1 : 0
                            visible: opacity > 0
                            Behavior on opacity { NumberAnimation { duration: Theme.animFast } }
                        }
                    }

                    Rectangle {
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 16
                        color: Theme.borderSoft
                        opacity: 0.5
                        Layout.alignment: Qt.AlignVCenter
                    }

                    IconButton {
                        iconSource: Theme.icon(Theme.dark ? "sun" : "moon")
                        toolTip: Theme.dark ? "Switch to light theme" : "Switch to dark theme"
                        buttonSize: 28
                        Layout.alignment: Qt.AlignVCenter
                        onClicked: window.toggleTheme()
                    }

                    IconButton {
                        iconSource: Theme.icon("settings")
                        toolTip: "Settings"
                        buttonSize: 28
                        selected: Session.workspaceIndex === 4
                        Layout.alignment: Qt.AlignVCenter
                        onClicked: Session.workspaceIndex = 4
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
                    property bool deferFutureLoads: false
                    asynchronous: deferFutureLoads
                    source: window.workspaceFiles[Session.workspaceIndex]
                    visible: status === Loader.Ready
                    opacity: 1

                    onStatusChanged: {
                        if (status === Loader.Error) {
                            console.warn("workspaceLoader ERROR source:", source, "index:", Session.workspaceIndex);
                        } else if (status === Loader.Ready) {
                            console.log("workspaceLoader Ready", source);
                        }
                    }

                    onLoaded: {
                        if (!deferFutureLoads)
                            Qt.callLater(function() { workspaceLoader.deferFutureLoads = true; });
                    }
                }

                Rectangle {
                    anchors.fill: parent
                    color: Theme.window
                    visible: workspaceLoader.status === Loader.Loading
                    opacity: 1
                }

                LoadingState {
                    anchors.centerIn: parent
                    visible: workspaceLoader.status === Loader.Loading
                    running: visible
                    label: "Opening workspace"
                    variant: "Dots"
                    showElapsed: false
                }

                Rectangle {
                    anchors.fill: parent
                    color: "#1a1a1c"
                    visible: workspaceLoader.status === Loader.Error
                    ColumnLayout {
                        anchors.centerIn: parent
                        spacing: 8
                        Text { text: "Workspace failed to load"; color: Theme.error; font.family: Theme.uiFont; font.pixelSize: 12; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignHCenter }
                        Text { text: workspaceLoader.source.toString(); color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9; Layout.alignment: Qt.AlignHCenter }
                        Text { text: "Check console for QML errors — try Ctrl+1..5"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; Layout.alignment: Qt.AlignHCenter }
                        TextButton { text: "Reload Create"; Layout.alignment: Qt.AlignHCenter; onClicked: Session.workspaceIndex = 0 }
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
                Layout.preferredHeight: Theme.statusHeight + 1
                color: Theme.chrome

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: 1
                    color: Theme.borderSoft
                    opacity: 0.55
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 8

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
                        Layout.maximumWidth: 480
                    }

                    Item {
                        Layout.fillWidth: true
                    }

                    Text {
                        text: RuntimeMetrics.vulkanReady ? "Vulkan · " + RuntimeMetrics.graphicsDevice : "Vulkan initializing"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        elide: Text.ElideRight
                        Layout.maximumWidth: 320
                    }

                    Rectangle {
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 10
                        color: Theme.borderSoft
                        opacity: 0.5
                    }

                    Text {
                        text: "Local frontend"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                    }
                }
            }
        }
    }

    LoginPage {
        anchors.fill: parent
        visible: !AuthController.authenticated
        z: 1000
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

                Image {
                    source: Theme.appLogo
                    sourceSize: Qt.size(112, 112)
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    mipmap: true
                    Layout.preferredWidth: 56
                    Layout.preferredHeight: 56
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
                        text: "Scenario Engine for Real-world Vehicle Optimization"
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
