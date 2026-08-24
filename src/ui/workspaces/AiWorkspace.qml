pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import "../components"

Item {
    id: root

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "Assistant"
            subtitle: "A native Gemini conversation for Servo engineering work"
            iconSource: Theme.icon("assistant")
            Layout.fillWidth: true

            StatusBadge {
                text: AiChatController.configured ? AiChatController.statusText : "API key required"
                tone: AiChatController.errorText.length > 0
                      ? "error" : (AiChatController.busy ? "info" : "neutral")
            }

            TextButton {
                text: "New conversation"
                iconSource: Theme.icon("plus")
                compact: true
                enabled: AiChatController.count > 0 || AiChatController.busy
                onClicked: AiChatController.clearConversation()
            }
        }

        Rectangle {
            visible: AiChatController.errorText.length > 0
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? errorRow.implicitHeight + 16 : 0
            color: Theme.tintError

            RowLayout {
                id: errorRow
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 8
                spacing: 8

                SvgIcon {
                    source: Theme.icon("error")
                    iconSize: Theme.iconSm
                    color: Theme.error
                }

                Text {
                    Layout.fillWidth: true
                    text: AiChatController.errorText
                    color: Theme.error
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    wrapMode: Text.WordWrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                }

                IconButton {
                    iconSource: Theme.icon("close")
                    toolTip: "Dismiss"
                    buttonSize: 26
                    onClicked: AiChatController.clearError()
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
                anchors.fill: parent
                anchors.leftMargin: Math.max(18, (parent.width - 920) / 2)
                anchors.rightMargin: Math.max(18, (parent.width - 920) / 2)
                anchors.topMargin: 12
                anchors.bottomMargin: 14
                spacing: 12

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    EmptyState {
                        anchors.centerIn: parent
                        width: Math.min(520, parent.width - 24)
                        visible: AiChatController.count === 0 && !AiChatController.busy
                        iconSource: Theme.icon("assistant")
                        title: "Talk to Servo Assistant"
                        description: AiChatController.configured
                                     ? "Ask about reconstruction, diagnostics, experiments, or the current engineering workflow. Responses come from the configured Gemini API."
                                     : "Set GOOGLE_API_KEY or GEMINI_API_KEY in the environment and restart Servo. The UI will never simulate an AI response when no provider is connected."
                    }

                    ListView {
                        id: messageList
                        anchors.fill: parent
                        visible: AiChatController.count > 0 || AiChatController.busy
                        model: AiChatController
                        spacing: 6
                        clip: true
                        reuseItems: true
                        cacheBuffer: 320
                        topMargin: 8
                        bottomMargin: 8
                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                        }

                        property bool followTail: true

                        onMovementStarted: followTail = atYEnd
                        onMovementEnded: followTail = atYEnd
                        onCountChanged: {
                            if (followTail)
                                Qt.callLater(positionViewAtEnd);
                        }
                        onContentHeightChanged: {
                            if (followTail)
                                Qt.callLater(positionViewAtEnd);
                        }

                        add: Transition {
                            NumberAnimation {
                                property: "opacity"
                                from: 0
                                to: 1
                                duration: Theme.animBase
                                easing.type: Easing.OutCubic
                            }
                            NumberAnimation {
                                property: "y"
                                from: 8
                                duration: Theme.animMove
                                easing.type: Easing.OutCubic
                            }
                        }

                        delegate: Item {
                            id: messageDelegate
                            required property string author
                            required property string content
                            required property string timestamp

                            readonly property bool sentByUser: author === "user"

                            width: ListView.view.width
                            height: bubble.height + 8

                            Rectangle {
                                id: bubble
                                anchors.right: messageDelegate.sentByUser ? parent.right : undefined
                                anchors.left: messageDelegate.sentByUser ? undefined : parent.left
                                width: Math.min(650, Math.max(168, messageText.implicitWidth + 28))
                                height: messageColumn.implicitHeight + 18
                                radius: 14
                                color: messageDelegate.sentByUser ? Theme.selection : Theme.panelRaised
                                border.width: messageDelegate.sentByUser ? 0 : 1
                                border.color: Theme.borderSoft

                                ColumnLayout {
                                    id: messageColumn
                                    anchors.fill: parent
                                    anchors.leftMargin: 14
                                    anchors.rightMargin: 14
                                    anchors.topMargin: 9
                                    anchors.bottomMargin: 8
                                    spacing: 5

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 7

                                        Text {
                                            text: messageDelegate.sentByUser ? "YOU" : "SERVO"
                                            color: messageDelegate.sentByUser ? Theme.text : Theme.textSecondary
                                            font.family: Theme.uiFont
                                            font.pixelSize: 8
                                            font.weight: Font.DemiBold
                                            font.letterSpacing: 0.7
                                        }

                                        Item {
                                            Layout.fillWidth: true
                                        }

                                        Text {
                                            text: messageDelegate.timestamp
                                            color: Theme.textMuted
                                            font.family: Theme.monoFont
                                            font.pixelSize: 8
                                        }
                                    }

                                    Text {
                                        id: messageText
                                        Layout.fillWidth: true
                                        text: messageDelegate.content
                                        color: Theme.text
                                        font.family: Theme.uiFont
                                        font.pixelSize: 11
                                        lineHeight: 1.25
                                        wrapMode: Text.Wrap
                                        textFormat: Text.PlainText
                                    }
                                }
                            }
                        }

                        footer: Item {
                            width: messageList.width
                            height: AiChatController.busy ? 44 : 0

                            LoadingState {
                                anchors.left: parent.left
                                anchors.leftMargin: 14
                                anchors.verticalCenter: parent.verticalCenter
                                running: AiChatController.busy
                                label: "Thinking"
                                variant: "Dots"
                            }
                        }
                    }
                }

                AiChatInput {
                    id: chatInput
                    Layout.fillWidth: true
                    Layout.maximumWidth: 760
                    Layout.alignment: Qt.AlignHCenter
                    models: AiChatController.modelNames
                    efforts: AiChatController.effortNames
                    attachments: AiChatController.pendingAttachments
                    maxAttachments: AiChatController.maxAttachments
                    busy: AiChatController.busy
                    backendConfigured: AiChatController.configured

                    onAttachRequested: attachmentDialog.open()
                    onRemoveAttachmentRequested: index => AiChatController.removeAttachment(index)
                    onStopRequested: AiChatController.cancel()
                    onSendRequested: (prompt, modelName, effortName) => {
                        if (AiChatController.sendMessage(prompt, modelName, effortName))
                            chatInput.clearPrompt();
                    }
                }
            }
        }
    }

    FileDialog {
        id: attachmentDialog
        title: "Attach images"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Images (*.png *.jpg *.jpeg *.webp *.bmp)", "All files (*)"]
        onAccepted: AiChatController.addAttachments(selectedFiles)
    }
}
