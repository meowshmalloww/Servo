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

    width: 1600
    height: 960
    minimumWidth: 1280
    minimumHeight: 720
    visible: true
    title: Session.projectOpen ? "Servo - " + Session.projectName : "Servo"
    color: Theme.window

    readonly property var workspaceNames: [
        "Prepare", "Worlds", "Runs", "Diagnose", "Train", "Verify", "Capabilities"
    ]
    readonly property var workspaceFiles: [
        "workspaces/PrepareWorkspace.qml",
        "workspaces/WorldsWorkspace.qml",
        "workspaces/RunsWorkspace.qml",
        "workspaces/DiagnoseWorkspace.qml",
        "workspaces/TrainWorkspace.qml",
        "workspaces/VerifyWorkspace.qml",
        "workspaces/CapabilitiesWorkspace.qml"
    ]

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
        id: settings
        category: "Workspace"
        property int selectedWorkspace: 0
    }

    Component.onCompleted: Session.workspaceIndex = Math.max(0, Math.min(6, settings.selectedWorkspace))
    Connections {
        target: Session
        function onWorkspaceIndexChanged() { settings.selectedWorkspace = Session.workspaceIndex }
        function onOpenProjectRequested() { projectDialog.open() }
        function onImportRecordingRequested() { recordingDialog.open() }
    }

    Shortcut { sequence: "Ctrl+O"; onActivated: projectDialog.open() }
    Shortcut { sequence: "Ctrl+1"; onActivated: Session.workspaceIndex = 0 }
    Shortcut { sequence: "Ctrl+2"; onActivated: Session.workspaceIndex = 1 }
    Shortcut { sequence: "Ctrl+3"; onActivated: Session.workspaceIndex = 2 }
    Shortcut { sequence: "Ctrl+4"; onActivated: Session.workspaceIndex = 3 }
    Shortcut { sequence: "Ctrl+5"; onActivated: Session.workspaceIndex = 4 }
    Shortcut { sequence: "Ctrl+6"; onActivated: Session.workspaceIndex = 5 }
    Shortcut { sequence: "Ctrl+7"; onActivated: Session.workspaceIndex = 6 }

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

            contentItem: Text {
                text: menuItem.text
                color: menuItem.highlighted ? Theme.text : Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: 11
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }

            background: Rectangle {
                color: menuItem.highlighted ? Theme.panelHover : "transparent"
            }
        }

        Menu {
            title: "File"
            Action { text: "Open Project..."; shortcut: "Ctrl+O"; onTriggered: projectDialog.open() }
            Action { text: "Close Project"; enabled: Session.projectOpen; onTriggered: Session.closeProject() }
            MenuSeparator { }
            Action { text: "Quit"; shortcut: StandardKey.Quit; onTriggered: window.close() }
        }

        Menu {
            title: "View"
            Repeater {
                model: window.workspaceNames
                MenuItem {
                    required property int index
                    required property string modelData
                    text: modelData
                    checkable: true
                    checked: Session.workspaceIndex === index
                    onTriggered: Session.workspaceIndex = index
                }
            }
        }

        Menu {
            title: "Window"
            Action {
                text: "Full Screen"
                shortcut: "F11"
                onTriggered: window.visibility = window.visibility === Window.FullScreen
                             ? Window.Windowed : Window.FullScreen
            }
        }

        Menu {
            title: "Help"
            Action { text: "About Servo"; onTriggered: aboutDialog.open() }
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
                anchors.leftMargin: 13
                anchors.rightMargin: 9
                spacing: 0

                RowLayout {
                    Layout.preferredWidth: 270
                    Layout.fillHeight: true
                    spacing: 9

                    SvgIcon { source: Theme.icon("app"); iconSize: 24 }

                    Text {
                        text: "SERVO"
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 17
                        font.weight: Font.Bold
                        font.letterSpacing: 1.0
                    }

                    Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 24; color: Theme.border }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        Text {
                            text: Session.projectOpen ? Session.projectName : "No project open"
                            color: Session.projectOpen ? Theme.textSecondary : Theme.textMuted
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }

                        Text {
                            text: Session.projectOpen ? Session.fileName(Session.projectUrl) : "Open a .servo project to begin"
                            color: Theme.textMuted
                            font.family: Theme.monoFont
                            font.pixelSize: 8
                            elide: Text.ElideMiddle
                            Layout.fillWidth: true
                        }
                    }
                }

                Item { Layout.fillWidth: true }

                Repeater {
                    model: window.workspaceNames

                    TopTab {
                        required property int index
                        required property string modelData
                        text: modelData
                        current: Session.workspaceIndex === index
                        onClicked: Session.workspaceIndex = index
                    }
                }

                Item { Layout.fillWidth: true }

                RowLayout {
                    Layout.preferredWidth: 230
                    Layout.alignment: Qt.AlignRight
                    spacing: 7

                    StatusBadge {
                        visible: Session.projectOpen
                        text: "Local project"
                    }

                    TextButton {
                        text: "Open Project"
                        iconSource: Theme.icon("open")
                        onClicked: projectDialog.open()
                    }
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

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.statusHeight
            color: Theme.chrome
            border.width: 1
            border.color: Theme.borderSoft

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 9

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
                    Layout.maximumWidth: 620
                }

                Item { Layout.fillWidth: true }

                Text {
                    text: "Qt RHI"
                    color: Theme.textMuted
                    font.family: Theme.uiFont
                    font.pixelSize: 9
                }

                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 12; color: Theme.border }

                Text {
                    text: "Display-synchronized  /  UI target up to " + Session.targetUiFrameRate + " Hz"
                    color: Theme.textMuted
                    font.family: Theme.monoFont
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

    Popup {
        id: aboutDialog
        width: 420
        height: 230
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

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 18
                spacing: 8

                Text { text: "SERVO"; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 20; font.weight: Font.Bold }
                Text {
                    text: "Simulation Environment for Robotic Validation and Optimization"
                    color: Theme.textSecondary
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                Text { text: "Qt 6 / QML / C++  |  GPL-3.0-only"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9 }
                Item { Layout.fillHeight: true }
                TextButton { text: "Close"; Layout.alignment: Qt.AlignRight; onClicked: aboutDialog.close() }
            }
        }
    }
}
