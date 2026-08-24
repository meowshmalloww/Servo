import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import QtQuick.Templates as T
import "."

T.Popup {
    id: root

    width: Math.min(520, (parent ? parent.width : 552) - 32)
    height: Math.min(500, (parent ? parent.height : 532) - 32)
    modal: true
    focus: true
    padding: 0
    popupType: T.Popup.Item
    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside

    component SettingRow: Rectangle {
        id: settingRow
        property string title: ""
        property string description: ""
        property string actionText: ""
        property url actionIcon
        property bool selected: false
        signal triggered()

        Layout.fillWidth: true
        Layout.preferredHeight: 60
        color: Theme.panelRaised
        radius: Theme.cornerCard - 3

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 11
            anchors.rightMargin: 8
            spacing: 12

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 2

                Text {
                    Layout.fillWidth: true
                    text: settingRow.title
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 11
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

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.animBase; easing.type: Easing.OutCubic }
        NumberAnimation { property: "scale"; from: 0.94; to: 1; duration: Theme.animSlow; easing.type: Easing.OutCubic }
    }

    exit: Transition {
        NumberAnimation { property: "opacity"; to: 0; duration: Theme.animFast; easing.type: Easing.InCubic }
        NumberAnimation { property: "scale"; to: 0.96; duration: Theme.animFast; easing.type: Easing.InCubic }
    }

    background: Rectangle {
        radius: Theme.cornerPopup
        color: Theme.panel
        border.width: 1
        border.color: Theme.borderStrong
    }

    contentItem: ColumnLayout {
        spacing: 0

        PanelHeader {
            title: "Settings"
            subtitle: "Local interface preferences"
            actionIcon: Theme.icon("close")
            actionToolTip: "Close"
            Layout.fillWidth: true
            onActionTriggered: root.close()
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            ColumnLayout {
                width: parent.width
                spacing: 6

                Text {
                    text: "INTERFACE"
                    color: Theme.textMuted
                    font.family: Theme.uiFont
                    font.pixelSize: 9
                    font.weight: Font.DemiBold
                    font.letterSpacing: 0.8
                    Layout.topMargin: 14
                    Layout.leftMargin: 16
                    Layout.bottomMargin: 1
                }

                SettingRow {
                    Layout.leftMargin: 16
                    Layout.rightMargin: 16
                    title: "Appearance"
                    description: "Switch between the dark and light interface theme."
                    actionText: Theme.dark ? "Dark" : "Light"
                    actionIcon: Theme.icon(Theme.dark ? "moon" : "sun")
                    selected: true
                    onTriggered: Theme.dark = !Theme.dark
                }

                SettingRow {
                    Layout.leftMargin: 16
                    Layout.rightMargin: 16
                    title: "Performance readouts"
                    description: "Show presentation FPS, CPU, RAM, and the renderer API. Display refresh stays in the FPS tooltip."
                    actionText: Session.showPerformanceMetrics ? "Shown" : "Hidden"
                    selected: Session.showPerformanceMetrics
                    onTriggered: Session.showPerformanceMetrics = !Session.showPerformanceMetrics
                }

                SettingRow {
                    Layout.leftMargin: 16
                    Layout.rightMargin: 16
                    title: "Interface motion"
                    description: "Disable non-essential transitions, shimmer, and looping loading animation."
                    actionText: Theme.motionEnabled ? "On" : "Off"
                    selected: Theme.motionEnabled
                    onTriggered: Theme.motionEnabled = !Theme.motionEnabled
                }

                SettingRow {
                    Layout.leftMargin: 16
                    Layout.rightMargin: 16
                    title: "Workspace layout"
                    description: "Restore the current workspace panes to their default sizes."
                    actionText: "Reset panes"
                    onTriggered: Session.resetWorkspaceLayoutRequested()
                }

                Text {
                    text: "RENDERER"
                    color: Theme.textMuted
                    font.family: Theme.uiFont
                    font.pixelSize: 9
                    font.weight: Font.DemiBold
                    font.letterSpacing: 0.8
                    Layout.topMargin: 10
                    Layout.leftMargin: 16
                    Layout.bottomMargin: 1
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 40
                    Layout.leftMargin: 16
                    Layout.rightMargin: 16
                    color: Theme.field
                    radius: Theme.cornerControl

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 11
                        anchors.rightMargin: 11
                        spacing: 8

                        Text {
                            text: "Active Qt RHI backend"
                            color: Theme.textSecondary
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: RuntimeMetrics.graphicsApi
                            color: Theme.accent
                            font.family: Theme.monoFont
                            font.pixelSize: 10
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    Layout.leftMargin: 16
                    Layout.rightMargin: 16
                    Layout.bottomMargin: 14
                    text: "Servo requires Vulkan and verifies the active scene-graph API before showing the window. Startup fails explicitly when Vulkan is unavailable."
                    color: Theme.textMuted
                    font.family: Theme.uiFont
                    font.pixelSize: 9
                    wrapMode: Text.WordWrap
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 50
            color: Theme.panel

            TextButton {
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                text: "Done"
                tone: "primary"
                onClicked: root.close()
            }
        }
    }
}
