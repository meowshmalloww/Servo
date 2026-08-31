import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "."

Rectangle {
    id: root
    color: Theme.window

    function submit() {
        if (!AuthController.busy)
            AuthController.signIn(emailField.text, passwordField.text)
    }

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(420, parent.width - 48)
        spacing: 18

        Image {
            source: Theme.appLogo
            sourceSize: Qt.size(72, 72)
            Layout.preferredWidth: 56
            Layout.preferredHeight: 56
            Layout.alignment: Qt.AlignHCenter
            fillMode: Image.PreserveAspectFit
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
                text: "Sign in to Servo"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 22
                font.weight: Font.DemiBold
                Layout.alignment: Qt.AlignHCenter
            }
            Text {
                text: "Authenticate before opening worlds, simulations, and agentic campaigns."
                color: Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 11
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: form.implicitHeight + 40
            radius: Theme.cornerPanel
            color: Theme.panel
            border.width: 1
            border.color: Theme.borderSoft

            ColumnLayout {
                id: form
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: 20
                spacing: 12

                Text {
                    text: "Firebase account"
                    color: Theme.textSecondary
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                    font.letterSpacing: 0.6
                }

                TextInput {
                    id: emailField
                    placeholderText: "Email"
                    enabled: AuthController.configured && !AuthController.busy
                    inputMethodHints: Qt.ImhEmailCharactersOnly | Qt.ImhNoAutoUppercase
                    onAccepted: passwordField.forceActiveFocus()
                }

                TextInput {
                    id: passwordField
                    placeholderText: "Password"
                    enabled: AuthController.configured && !AuthController.busy
                    echoMode: TextInput.Password
                    onAccepted: root.submit()
                }

                Text {
                    Layout.fillWidth: true
                    visible: AuthController.lastError.length > 0
                    text: AuthController.lastError
                    color: Theme.error
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    wrapMode: Text.WordWrap
                }

                TextButton {
                    Layout.fillWidth: true
                    text: AuthController.busy ? "Verifying account..." : "Sign in"
                    tone: "primary"
                    enabled: AuthController.configured && !AuthController.busy
                             && emailField.text.length > 0 && passwordField.text.length > 0
                    onClicked: root.submit()
                }
            }
        }

        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 6
            SvgIcon {
                source: Theme.icon("shield")
                iconSize: Theme.iconXs
                color: Theme.textMuted
            }
            Text {
                text: AuthController.projectId.length > 0
                      ? "Firebase · " + AuthController.projectId
                      : "Firebase configuration required"
                color: Theme.textMuted
                font.family: Theme.monoFont
                font.pixelSize: 9
            }
        }
    }
}
