pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../components"

Item {
    id: root

    component SettingRow: Rectangle {
        id: settingRow
        property string title: ""
        property string description: ""
        property string actionText: ""
        property url actionIcon
        property bool selected: false
        signal triggered()

        Layout.fillWidth: true
        Layout.preferredHeight: 64
        color: Theme.panelRaised
        radius: Theme.cornerCard - 2
        border.width: 1
        border.color: Theme.borderSoft

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 10
            spacing: 12

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 3

                Text {
                    Layout.fillWidth: true
                    text: settingRow.title
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }

                Text {
                    Layout.fillWidth: true
                    text: settingRow.description
                    color: Theme.textMuted
                    font.family: Theme.uiFont
                    font.pixelSize: 9
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    lineHeight: 1.2
                }
            }

            TextButton {
                text: settingRow.actionText
                iconSource: settingRow.actionIcon
                selected: settingRow.selected
                compact: true
                Layout.alignment: Qt.AlignVCenter
                onClicked: settingRow.triggered()
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "Settings"
            subtitle: "Local interface preferences"
            helpText: "Appearance, motion, and workspace preferences. Renderer info is read-only."
            iconSource: Theme.icon("settings")
            Layout.fillWidth: true
        }

        ScrollView {
            id: settingsScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
                id: settingsContent
                width: settingsScroll.availableWidth
                spacing: 0

                // Centered max width 760 like Ai workspace for consistency
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.maximumWidth: 760
                    Layout.alignment: Qt.AlignHCenter
                    Layout.leftMargin: 20
                    Layout.rightMargin: 20
                    Layout.topMargin: 18
                    Layout.bottomMargin: 18
                    spacing: 16

                    Text {
                        text: "INTERFACE"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        font.weight: Font.DemiBold
                        font.letterSpacing: 0.9
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        SettingRow {
                            title: "Appearance"
                            description: "Switch between the dark and light interface theme."
                            actionText: Theme.dark ? "Dark" : "Light"
                            actionIcon: Theme.icon(Theme.dark ? "moon" : "sun")
                            selected: true
                            onTriggered: Theme.dark = !Theme.dark
                        }

                        SettingRow {
                            title: "Performance readouts"
                            description: "Show presentation FPS, CPU, RAM, and the renderer API. Display refresh stays in the FPS tooltip."
                            actionText: Session.showPerformanceMetrics ? "Shown" : "Hidden"
                            selected: Session.showPerformanceMetrics
                            onTriggered: Session.showPerformanceMetrics = !Session.showPerformanceMetrics
                        }

                        SettingRow {
                            title: "Interface motion"
                            description: "Disable non-essential transitions and looping loading animation."
                            actionText: Theme.motionEnabled ? "On" : "Off"
                            selected: Theme.motionEnabled
                            onTriggered: Theme.motionEnabled = !Theme.motionEnabled
                        }

                        SettingRow {
                            title: "Workspace layout"
                            description: "Restore the current workspace panes to their default sizes."
                            actionText: "Reset panes"
                            onTriggered: Session.resetWorkspaceLayoutRequested()
                        }
                    }

                    Text {
                        text: "SHORTCUTS"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        font.weight: Font.DemiBold
                        font.letterSpacing: 0.9
                        Layout.topMargin: 8
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: width >= 680 ? 2 : 1
                        columnSpacing: 8
                        rowSpacing: 8

                        Repeater {
                            model: [
                                {k:"Ctrl+O", d:"Open project"},
                                {k:"Ctrl+1..5", d:"Switch workspace"},
                                {k:"Ctrl+,", d:"Open Settings"},
                                {k:"F11", d:"Toggle fullscreen"},
                                {k:"Ctrl+`", d:"Toggle terminal drawer"},
                                {k:"WASD + E/Q", d:"Fly in Explore (focus viewport)"},
                                {k:"1..4", d:"Diagnostic Appearance/Depth/Structure/Coverage"},
                                {k:"R", d:"Reset Explore camera"}
                            ]
                            delegate: Rectangle {
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.preferredHeight: 42
                                color: Theme.field
                                radius: Theme.cornerControl
                                border.width: 1
                                border.color: Theme.borderSoft
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 12
                                    anchors.rightMargin: 12
                                    spacing: 10
                                    Text { text: modelData.k; color: Theme.text; font.family: Theme.monoFont; font.pixelSize: 9; font.weight: Font.DemiBold; Layout.preferredWidth: 92; elide: Text.ElideRight }
                                    Text { Layout.fillWidth: true; text: modelData.d; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9; elide: Text.ElideRight }
                                }
                            }
                        }
                    }

                    Text {
                        text: "STORAGE & PATHS"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        font.weight: Font.DemiBold
                        font.letterSpacing: 0.9
                        Layout.topMargin: 8
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 42
                            color: Theme.field
                            radius: Theme.cornerControl
                            border.width: 1
                            border.color: Theme.borderSoft
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 14
                                anchors.rightMargin: 10
                                spacing: 8
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Text { text: "Worlds on disk"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; elide: Text.ElideRight; Layout.fillWidth: true }
                                    Text { text: WorldLibraryModel.totalBytesText + " · " + WorldLibraryModel.totalCount + " worlds"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9; elide: Text.ElideRight; Layout.fillWidth: true }
                                }
                                TextButton { text: "Refresh"; iconSource: Theme.icon("refresh"); compact: true; onClicked: WorldLibraryModel.refresh() }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 42
                            color: Theme.field
                            radius: Theme.cornerControl
                            border.width: 1
                            border.color: Theme.borderSoft
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 14
                                anchors.rightMargin: 10
                                spacing: 8
                                Text { Layout.fillWidth: true; text: "Open reconstruction logs"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10 }
                                TextButton { text: "Logs"; iconSource: Theme.icon("folder"); compact: true; onClicked: Qt.openUrlExternally("file:///" + appSettings.fileName) }
                            }
                        }
                    }

                    Text {
                        text: "RENDERER"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        font.weight: Font.DemiBold
                        font.letterSpacing: 0.9
                        Layout.topMargin: 8
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 46
                        color: Theme.field
                        radius: Theme.cornerControl
                        border.width: 1
                        border.color: Theme.borderSoft

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 14
                            anchors.rightMargin: 14
                            spacing: 8

                            Text {
                                text: "Active Qt RHI backend"
                                color: Theme.textSecondary
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: RuntimeMetrics.graphicsApi + " · " + RuntimeMetrics.graphicsDeviceType
                                color: Theme.text
                                font.family: Theme.monoFont
                                font.pixelSize: 10
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                                Layout.maximumWidth: 260
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 38
                        color: Theme.field
                        radius: Theme.cornerControl
                        border.width: 1
                        border.color: Theme.borderSoft
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 14
                            anchors.rightMargin: 14
                            spacing: 8
                            Text { text: "Vulkan device"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; Layout.fillWidth: true; elide: Text.ElideMiddle }
                            Text { text: RuntimeMetrics.graphicsDevice; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9; elide: Text.ElideRight; Layout.maximumWidth: 280 }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Servo requires Vulkan and verifies the active scene-graph API before showing the window. Startup fails explicitly when Vulkan is unavailable."
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        wrapMode: Text.WordWrap
                        lineHeight: 1.3
                    }

                    Text {
                        text: "ABOUT"
                        color: Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        font.weight: Font.DemiBold
                        font.letterSpacing: 0.9
                        Layout.topMargin: 8
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 64
                        color: Theme.panelRaised
                        radius: Theme.cornerCard - 2
                        border.width: 1
                        border.color: Theme.borderSoft
                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 12
                            Image { source: Theme.appLogo; sourceSize: Qt.size(48,48); Layout.preferredWidth: 32; Layout.preferredHeight: 32; fillMode: Image.PreserveAspectFit; smooth: true; mipmap: true }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Text { text: "SERVO  ·  Scenario Engine for Real-world Vehicle Optimization"; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 10; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                                Text { text: "Qt 6.11 / QML / C++20  ·  GPL-3.0-only"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 9; Layout.fillWidth: true }
                            }
                            TextButton { text: "About"; iconSource: Theme.icon("info"); compact: true; onClicked: Session.workspaceIndex = 0 }
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
                    }
                }
            }
        }
    }
}
