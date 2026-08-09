import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../components"

Item {
    id: root

    readonly property bool compilerAvailable: false

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "Worlds"
            subtitle: "Executable reality: appearance, metric geometry, actors, road graph, sensors, and uncertainty"
            iconSource: Theme.icon("world")
            Layout.fillWidth: true

            TextButton {
                text: "Select Recording"
                iconSource: Theme.icon("camera")
                enabled: Session.projectOpen
                onClicked: Session.importRecordingRequested()
            }

            TextButton {
                text: "Compile World"
                iconSource: Theme.icon("build")
                tone: "primary"
                enabled: Session.recordingSelected && root.compilerAvailable
                toolTip: root.compilerAvailable ? "Compile selected recording" : "World compiler service is not connected"
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: SplitHandle { }

            Panel {
                SplitView.preferredWidth: 270
                SplitView.minimumWidth: 220
                SplitView.maximumWidth: 380

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "World Library"
                        subtitle: Session.worldModel === null ? "No model" : "Connected"
                        iconSource: Theme.icon("world")
                        Layout.fillWidth: true
                    }

                    EntityList {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: Session.worldModel
                        searchPlaceholder: "Search worlds"
                        emptyIcon: Theme.icon("world")
                        emptyTitle: "No compiled worlds"
                        emptyDescription: Session.recordingSelected
                                          ? "The selected recording has not been compiled into an executable world."
                                          : "Select an authorized recording, then compile appearance and deterministic simulation layers."
                    }

                    Rectangle {
                        visible: Session.recordingSelected
                        Layout.fillWidth: true
                        Layout.preferredHeight: 50
                        color: Theme.chrome
                        border.width: 1
                        border.color: Theme.borderSoft

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 9
                            anchors.rightMargin: 9
                            spacing: 8
                            SvgIcon { source: Theme.icon("camera"); iconSize: 14 }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 1
                                Text { text: "Selected source"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9 }
                                Text { text: Session.recordingName; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: 10; elide: Text.ElideMiddle; Layout.fillWidth: true }
                            }
                        }
                    }
                }
            }

            SplitView {
                orientation: Qt.Vertical
                SplitView.fillWidth: true
                SplitView.minimumWidth: 620
                handle: SplitHandle { }

                ViewportSurface {
                    SplitView.fillHeight: true
                    SplitView.minimumHeight: 380
                    title: "World View"
                    available: false
                    emptyTitle: "No compiled world open"
                    emptyDescription: "The viewport activates only after a world service publishes a render scene."
                }

                Timeline {
                    SplitView.preferredHeight: 110
                    SplitView.minimumHeight: 86
                    SplitView.maximumHeight: 180
                    available: false
                }

                BottomDrawer {
                    SplitView.preferredHeight: implicitHeight
                    SplitView.minimumHeight: 34
                    SplitView.maximumHeight: 220
                    tabs: ["Compiler", "Validation", "Artifacts"]
                }
            }

            Panel {
                SplitView.preferredWidth: 310
                SplitView.minimumWidth: 270
                SplitView.maximumWidth: 430

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "World Inspector"
                        subtitle: "No selection"
                        iconSource: Theme.icon("settings")
                        Layout.fillWidth: true
                    }

                    ScrollView {
                        id: inspectorScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        Column {
                            width: inspectorScroll.availableWidth

                            Section {
                                title: "Source"
                                PropertyRow { label: "Recording"; labelWidth: 92; TextInput { text: Session.recordingName; placeholderText: "No source"; readOnly: true } }
                                PropertyRow { label: "Calibration"; labelWidth: 92; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "Duration"; labelWidth: 92; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                            }

                            Section {
                                title: "Geometry"
                                PropertyRow { label: "Representation"; labelWidth: 92; TextInput { placeholderText: "No compiled geometry"; readOnly: true } }
                                PropertyRow { label: "Metric scale"; labelWidth: 92; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "Collision"; labelWidth: 92; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                            }

                            Section {
                                title: "Scene Structure"
                                PropertyRow { label: "Actors"; labelWidth: 92; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "Road graph"; labelWidth: 92; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                                PropertyRow { label: "Sensors"; labelWidth: 92; TextInput { placeholderText: "Unavailable"; readOnly: true } }
                            }

                            Section {
                                title: "Uncertainty"
                                PropertyRow { label: "Coverage"; labelWidth: 92; TextInput { placeholderText: "No uncertainty map"; readOnly: true } }
                                PropertyRow { label: "Threshold"; labelWidth: 92; TextInput { placeholderText: "Not configured"; readOnly: true } }
                            }
                        }
                    }
                }
            }
        }
    }
}
