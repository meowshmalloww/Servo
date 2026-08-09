import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import "."

T.Popup {
    id: root

    width: 500
    height: 340
    modal: true
    focus: true
    padding: 0
    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside

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

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 16
            spacing: 0

            Text {
                text: "INTERFACE"
                color: Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 9
                font.weight: Font.DemiBold
                font.letterSpacing: 0.8
                Layout.bottomMargin: 7
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 44
                color: Theme.panelRaised
                border.width: 1
                border.color: Theme.borderSoft
                radius: Theme.cornerControl

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 11
                    anchors.rightMargin: 8
                    spacing: 8

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Text {
                            text: "Performance readouts"
                            color: Theme.text
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                        }
                        Text {
                            text: "Show measured FPS activity, CPU, RAM, and renderer API in the top bar."
                            color: Theme.textMuted
                            font.family: Theme.uiFont
                            font.pixelSize: 9
                        }
                    }

                    TextButton {
                        text: Session.showPerformanceMetrics ? "Shown" : "Hidden"
                        compact: true
                        onClicked: Session.showPerformanceMetrics = !Session.showPerformanceMetrics
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 44
                Layout.topMargin: 6
                color: Theme.panelRaised
                border.width: 1
                border.color: Theme.borderSoft
                radius: Theme.cornerControl

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 11
                    anchors.rightMargin: 8
                    spacing: 8

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Text {
                            text: "Workspace layout"
                            color: Theme.text
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                        }
                        Text {
                            text: "Restore the current workspace panes to their default sizes."
                            color: Theme.textMuted
                            font.family: Theme.uiFont
                            font.pixelSize: 9
                        }
                    }

                    TextButton {
                        text: "Reset panes"
                        compact: true
                        onClicked: Session.resetWorkspaceLayoutRequested()
                    }
                }
            }

            Text {
                text: "RENDERER"
                color: Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 9
                font.weight: Font.DemiBold
                font.letterSpacing: 0.8
                Layout.topMargin: 18
                Layout.bottomMargin: 7
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 48
                color: Theme.field
                border.width: 1
                border.color: Theme.borderSoft

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
                    Item {
                        Layout.fillWidth: true
                    }
                    Text {
                        text: RuntimeMetrics.graphicsApi
                        color: Theme.text
                        font.family: Theme.monoFont
                        font.pixelSize: 10
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                Layout.topMargin: 8
                text: "The renderer backend is selected before window creation. Vulkan integration remains available without forcing unsupported hardware into a failed startup."
                color: Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 9
                wrapMode: Text.WordWrap
            }

            Item {
                Layout.fillHeight: true
            }

            TextButton {
                text: "Done"
                Layout.alignment: Qt.AlignRight
                onClicked: root.close()
            }
        }
    }

    enter: Transition {}
    exit: Transition {}
}
