pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "."

Rectangle {
    id: root

    property var models: []
    property var efforts: []
    property var attachments: []
    property int maxAttachments: 6
    property bool busy: false
    property bool backendConfigured: false
    readonly property string selectedModel: modelField.currentIndex >= 0
                                                    ? String(modelField.currentText) : ""
    readonly property string selectedEffort: effortField.currentIndex >= 0
                                                     ? String(effortField.currentText) : "Medium"

    signal sendRequested(string prompt, string modelName, string effortName)
    signal stopRequested()
    signal attachRequested()
    signal removeAttachmentRequested(int index)

    function clearPrompt() {
        promptArea.text = "";
    }

    function trySubmit() {
        if (busy) {
            stopRequested();
            return;
        }
        const prompt = promptArea.text.trim();
        if (prompt.length === 0 || !backendConfigured)
            return;
        sendRequested(prompt, selectedModel, selectedEffort);
    }

    implicitWidth: 720
    implicitHeight: composerLayout.implicitHeight + 20
    radius: 18
    color: Theme.panelRaised
    border.width: promptArea.activeFocus ? 1 : 0
    border.color: Theme.selectionBorder

    Behavior on implicitHeight {
        enabled: Theme.motionEnabled
        NumberAnimation {
            duration: Theme.animMove
            easing.type: Easing.OutCubic
        }
    }

    ColumnLayout {
        id: composerLayout
        anchors.fill: parent
        anchors.margins: 10
        spacing: 7

        Flickable {
            visible: root.attachments.length > 0
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 48 : 0
            contentWidth: attachmentRow.implicitWidth
            contentHeight: height
            flickableDirection: Flickable.HorizontalFlick
            boundsBehavior: Flickable.StopAtBounds
            clip: true

            Row {
                id: attachmentRow
                height: parent.height
                spacing: 7

                Repeater {
                    model: root.attachments

                    Rectangle {
                        id: attachmentChip
                        required property int index
                        required property var modelData

                        width: Math.min(188, chipRow.implicitWidth + 14)
                        height: 44
                        radius: Theme.cornerCard - 2
                        color: Theme.field

                        RowLayout {
                            id: chipRow
                            anchors.fill: parent
                            anchors.leftMargin: 4
                            anchors.rightMargin: 3
                            spacing: 6

                            Image {
                                Layout.preferredWidth: 36
                                Layout.preferredHeight: 36
                                source: attachmentChip.modelData.url
                                sourceSize: Qt.size(48, 48)
                                asynchronous: true
                                fillMode: Image.PreserveAspectCrop
                            }

                            Text {
                                Layout.fillWidth: true
                                Layout.maximumWidth: 105
                                text: String(attachmentChip.modelData.name)
                                color: Theme.textSecondary
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                                elide: Text.ElideMiddle
                            }

                            IconButton {
                                iconSource: Theme.icon("close")
                                toolTip: "Remove attachment"
                                buttonSize: 24
                                onClicked: root.removeAttachmentRequested(attachmentChip.index)
                            }
                        }

                        NumberAnimation on opacity {
                            from: 0
                            to: 1
                            duration: Theme.animBase
                            running: Theme.motionEnabled
                        }
                    }
                }
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(58, Math.min(150, promptArea.contentHeight + 22))
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.policy: promptArea.contentHeight > 128
                                       ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff

            TextArea {
                id: promptArea
                placeholderText: root.backendConfigured
                                 ? "Ask Servo anything..."
                                 : "Configure a Gemini API key to start chatting"
                enabled: !root.busy
                wrapMode: TextArea.Wrap
                selectByMouse: true
                leftPadding: 4
                rightPadding: 4
                topPadding: 5
                bottomPadding: 5
                color: Theme.text
                placeholderTextColor: Theme.textMuted
                selectionColor: Theme.selection
                selectedTextColor: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 12
                background: null

                Keys.onReturnPressed: event => {
                    if (!(event.modifiers & Qt.ShiftModifier)) {
                        root.trySubmit();
                        event.accepted = true;
                    }
                }
                Keys.onEnterPressed: event => {
                    if (!(event.modifiers & Qt.ShiftModifier)) {
                        root.trySubmit();
                        event.accepted = true;
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            SelectField {
                id: modelField
                Layout.preferredWidth: 168
                Layout.preferredHeight: 28
                Layout.fillWidth: false
                model: root.models
                currentIndex: root.models.length > 0 ? 0 : -1
                enabled: !root.busy
            }

            SelectField {
                id: effortField
                Layout.preferredWidth: 102
                Layout.preferredHeight: 28
                Layout.fillWidth: false
                model: root.efforts
                currentIndex: root.efforts.length > 1 ? 1 : 0
                enabled: !root.busy
            }

            Item {
                Layout.fillWidth: true
            }

            Text {
                visible: !root.backendConfigured
                text: "API key required"
                color: Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 9
            }

            IconButton {
                iconSource: Theme.icon("plus")
                toolTip: "Attach images"
                buttonSize: 28
                enabled: !root.busy && root.attachments.length < root.maxAttachments
                onClicked: root.attachRequested()
            }

            TextButton {
                text: root.busy ? "Stop" : "Send"
                iconSource: Theme.icon(root.busy ? "stop" : "forward")
                tone: root.busy ? "danger" : "primary"
                compact: true
                enabled: root.busy
                         || (root.backendConfigured && promptArea.text.trim().length > 0)
                onClicked: root.trySubmit()
            }
        }
    }
}
