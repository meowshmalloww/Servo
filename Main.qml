import QtCore
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

ApplicationWindow {
    id: window

    width: 1600
    height: 960
    minimumWidth: 1100
    minimumHeight: 700
    visible: true
    title: qsTr("Servo — Urban Occlusion Study")
    color: Theme.window

    property int currentWorkspace: 1
    property var workspaceNames: ["Prepare", "Simulate", "Diagnose", "Train", "Verify"]
    property var workspaceFiles: [
        "PrepareWorkspace.qml",
        "SimulateWorkspace.qml",
        "DiagnoseWorkspace.qml",
        "TrainWorkspace.qml",
        "VerifyWorkspace.qml"
    ]
    property string toastMessage: ""

    palette.window: Theme.window
    palette.windowText: Theme.text
    palette.base: Theme.field
    palette.alternateBase: Theme.panelRaised
    palette.text: Theme.text
    palette.button: Theme.surface
    palette.buttonText: Theme.text
    palette.highlight: Theme.accentDim
    palette.highlightedText: Theme.text
    palette.toolTipBase: Theme.panelRaised
    palette.toolTipText: Theme.text
    palette.placeholderText: Theme.textMuted

    Settings {
        id: appSettings
        category: "ServoFrontend"
        property int workspaceIndex: 1
    }

    Component.onCompleted: currentWorkspace = Math.max(0, Math.min(4, appSettings.workspaceIndex))
    onCurrentWorkspaceChanged: appSettings.workspaceIndex = currentWorkspace

    Shortcut { sequence: "Ctrl+1"; onActivated: window.currentWorkspace = 0 }
    Shortcut { sequence: "Ctrl+2"; onActivated: window.currentWorkspace = 1 }
    Shortcut { sequence: "Ctrl+3"; onActivated: window.currentWorkspace = 2 }
    Shortcut { sequence: "Ctrl+4"; onActivated: window.currentWorkspace = 3 }
    Shortcut { sequence: "Ctrl+5"; onActivated: window.currentWorkspace = 4 }
    Shortcut { sequence: "Ctrl+,"; onActivated: settingsPopup.open() }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        MenuBar {
            id: menuBar
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.menuHeight
            font.family: Theme.uiFont
            font.pixelSize: 12

            background: Rectangle {
                color: Theme.chrome
                border.width: 1
                border.color: Theme.border
            }

            delegate: MenuBarItem {
                id: menuItem
                implicitHeight: Theme.menuHeight

                contentItem: Text {
                    text: menuItem.text
                    color: menuItem.highlighted ? Theme.text : Theme.textSecondary
                    font: menuItem.font
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }

                background: Rectangle {
                    color: menuItem.highlighted ? Theme.surfaceHover : "transparent"
                }
            }

            Menu {
                title: qsTr("File")
                Action { text: qsTr("New study…") }
                Action { text: qsTr("Open study…") }
                MenuSeparator { }
                Action { text: qsTr("Save study"); shortcut: StandardKey.Save }
                Action { text: qsTr("Save study as…") }
                MenuSeparator { }
                Action { text: qsTr("Exit"); onTriggered: window.close() }
            }

            Menu {
                title: qsTr("Edit")
                Action { text: qsTr("Undo"); shortcut: StandardKey.Undo }
                Action { text: qsTr("Redo"); shortcut: StandardKey.Redo }
                MenuSeparator { }
                Action { text: qsTr("Preferences…"); shortcut: "Ctrl+,"; onTriggered: settingsPopup.open() }
            }

            Menu {
                title: qsTr("View")
                Repeater {
                    model: window.workspaceNames
                    MenuItem {
                        required property int index
                        required property string modelData
                        text: modelData + " workspace"
                        checkable: true
                        checked: window.currentWorkspace === index
                        onTriggered: window.currentWorkspace = index
                    }
                }
            }

            Menu {
                title: qsTr("Run")
                Action { text: qsTr("Run study"); shortcut: "F6"; onTriggered: runStudy() }
                Action { text: qsTr("Pause"); shortcut: "F7" }
                Action { text: qsTr("Stop"); shortcut: "Shift+F7" }
            }

            Menu {
                title: qsTr("Tools")
                Action { text: qsTr("Policy adapters") }
                Action { text: qsTr("Sensor calibration") }
                Action { text: qsTr("Compute targets") }
            }

            Menu {
                title: qsTr("Window")
                Action { text: qsTr("Reset layout"); onTriggered: showToast("Workspace layout reset") }
                Action { text: qsTr("Toggle full screen"); shortcut: "F11"; onTriggered: window.visibility = window.visibility === Window.FullScreen ? Window.Windowed : Window.FullScreen }
            }

            Menu {
                title: qsTr("Help")
                Action { text: qsTr("Keyboard shortcuts") }
                Action { text: qsTr("About Servo"); onTriggered: aboutPopup.open() }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.toolbarHeight
            color: Theme.chrome
            border.width: 1
            border.color: Theme.border

            RowLayout {
                anchors.fill: parent
                spacing: 0

                Item {
                    Layout.preferredWidth: 314
                    Layout.fillHeight: true

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 12
                        spacing: 10

                        Text {
                            text: "SERVO"
                            color: Theme.text
                            font.family: Theme.uiFont
                            font.pixelSize: 18
                            font.weight: Font.Bold
                            font.letterSpacing: 1.2
                        }

                        Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 24; color: Theme.borderStrong }

                        ColumnLayout {
                            spacing: 0
                            Layout.fillWidth: true

                            Text {
                                text: "Urban Occlusion Study"
                                color: Theme.text
                                font.family: Theme.uiFont
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }

                            Text {
                                text: "local prototype  ·  v0.2"
                                color: Theme.textMuted
                                font.family: Theme.monoFont
                                font.pixelSize: 9
                            }
                        }
                    }
                }

                Item { Layout.fillWidth: true }

                Repeater {
                    model: window.workspaceNames

                    WorkspaceTab {
                        required property int index
                        required property string modelData
                        text: modelData
                        current: window.currentWorkspace === index
                        onClicked: window.currentWorkspace = index
                    }
                }

                Item { Layout.fillWidth: true }

                RowLayout {
                    Layout.rightMargin: 10
                    spacing: 7

                    StatusDot { dotColor: Theme.green }

                    Text {
                        text: "LOCAL"
                        color: Theme.textMuted
                        font.family: Theme.monoFont
                        font.pixelSize: 9
                    }

                    AppButton {
                        text: "Run study"
                        glyph: "▶"
                        tone: "primary"
                        onClicked: runStudy()
                    }

                    IconButton {
                        glyph: "⚙"
                        toolTip: "Preferences"
                        onClicked: settingsPopup.open()
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            ActivityRail {
                Layout.preferredWidth: 52
                Layout.fillHeight: true
                currentIndex: window.currentWorkspace
                onRequested: index => window.currentWorkspace = index
                onSettingsRequested: settingsPopup.open()
            }

            Loader {
                id: workspaceLoader
                Layout.fillWidth: true
                Layout.fillHeight: true
                asynchronous: false
                source: window.workspaceFiles[window.currentWorkspace]

                onStatusChanged: {
                    if (status === Loader.Error)
                        window.showToast("Unable to load " + window.workspaceNames[window.currentWorkspace])
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.statusHeight
            color: Theme.chrome
            border.width: 1
            border.color: Theme.border

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 11
                anchors.rightMargin: 10
                spacing: 9

                StatusDot { dotColor: Theme.green; pulse: window.currentWorkspace === 1 || window.currentWorkspace === 3 }

                Text {
                    text: window.workspaceNames[window.currentWorkspace]
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                }

                Text { text: "Ready"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10 }
                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 14; color: Theme.border }
                Text { text: "58 FPS"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 9 }
                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 14; color: Theme.border }
                Text { text: "GPU 72%"; color: Theme.textSecondary; font.family: Theme.monoFont; font.pixelSize: 9 }
                Text { text: "VRAM 9.1 / 12.0 GB"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9 }

                Item { Layout.fillWidth: true }

                Text {
                    text: "REALITY DEBT"
                    color: Theme.textMuted
                    font.family: Theme.uiFont
                    font.pixelSize: 9
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "18.4%"
                    color: Theme.accentBright
                    font.family: Theme.monoFont
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                }

                Rectangle {
                    Layout.preferredWidth: 92
                    Layout.preferredHeight: 4
                    color: Theme.borderStrong

                    Rectangle { width: parent.width * 0.184; height: parent.height; color: Theme.accent }
                }
            }
        }
    }

    Popup {
        id: settingsPopup
        width: 430
        height: 330
        anchors.centerIn: Overlay.overlay
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        padding: 0

        background: Rectangle {
            color: Theme.panelRaised
            border.width: 1
            border.color: Theme.borderStrong
        }

        contentItem: ColumnLayout {
            spacing: 0

            PanelHeader {
                title: "Frontend preferences"
                actionGlyph: "×"
                actionToolTip: "Close"
                Layout.fillWidth: true
                onActionTriggered: settingsPopup.close()
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 16
                spacing: 12

                Text {
                    text: "Appearance"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "Servo uses a fixed near-black engine theme. Accent colors are reserved for selection, telemetry, warnings, and verification state."
                    color: Theme.textSecondary
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }

                PropertyRow {
                    label: "UI scale"
                    UiComboBox { model: ["100%", "110%", "125%"] }
                }

                PropertyRow {
                    label: "Panel density"
                    UiComboBox { model: ["Compact", "Comfortable"] }
                }

                Item { Layout.fillHeight: true }

                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    AppButton { text: "Close"; onClicked: settingsPopup.close() }
                }
            }
        }
    }

    Popup {
        id: aboutPopup
        width: 390
        height: 230
        anchors.centerIn: Overlay.overlay
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        padding: 0

        background: Rectangle { color: Theme.panelRaised; border.width: 1; border.color: Theme.borderStrong }

        contentItem: ColumnLayout {
            spacing: 12
            anchors.margins: 20

            Text { text: "SERVO"; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 24; font.weight: Font.Bold }
            Text { text: "Simulation Environment for Robotic Validation and Optimization"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            Text { text: "Frontend prototype · Qt 6 / QML · GPL-3.0-only"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 10 }
            Item { Layout.fillHeight: true }
            AppButton { text: "Close"; Layout.alignment: Qt.AlignRight; onClicked: aboutPopup.close() }
        }
    }

    Rectangle {
        id: toast
        visible: opacity > 0
        opacity: 0
        z: 1000
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Theme.statusHeight + 18
        width: Math.min(520, toastText.implicitWidth + 28)
        height: 34
        radius: 2
        color: Theme.panelRaised
        border.width: 1
        border.color: Theme.borderStrong

        Text {
            id: toastText
            anchors.centerIn: parent
            text: window.toastMessage
            color: Theme.text
            font.family: Theme.uiFont
            font.pixelSize: 11
        }

        Behavior on opacity { NumberAnimation { duration: 140 } }
    }

    Timer {
        id: toastTimer
        interval: 2200
        onTriggered: toast.opacity = 0
    }

    function showToast(message) {
        toastMessage = message
        toast.opacity = 1
        toastTimer.restart()
    }

    function runStudy() {
        currentWorkspace = 1
        showToast("Run 0248 queued in the frontend prototype")
    }
}
