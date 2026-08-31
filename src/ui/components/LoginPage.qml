import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "."

Rectangle {
    id: root
    color: Theme.window
    clip: true

    property bool revealPassword: false

    function submit() {
        if (!AuthController.busy)
            AuthController.signIn(emailField.text, passwordField.text)
    }

    // Quiet orbital motion gives the gateway a sense of a live control plane
    // without turning authentication into a decorative landing page.
    Rectangle {
        width: 620
        height: width
        radius: width / 2
        color: "transparent"
        border.width: 1
        border.color: Theme.borderSoft
        opacity: 0.55
        x: -220
        y: parent.height - 310
        transform: Rotation {
            id: orbitRotation
            origin.x: 310
            origin.y: 310
            angle: 0
            NumberAnimation on angle {
                from: 0
                to: 360
                duration: 48000
                loops: Animation.Infinite
                running: Theme.motionEnabled && root.visible
            }
        }
        Rectangle {
            width: 8
            height: 8
            radius: 4
            color: Theme.textMuted
            anchors.top: parent.top
            anchors.horizontalCenter: parent.horizontalCenter
        }
    }

    Rectangle {
        width: 440
        height: width
        radius: width / 2
        color: "transparent"
        border.width: 1
        border.color: Theme.borderSoft
        opacity: 0.32
        anchors.right: parent.right
        anchors.rightMargin: -190
        anchors.top: parent.top
        anchors.topMargin: -180
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Math.max(36, parent.width * 0.075)
        anchors.rightMargin: Math.max(36, parent.width * 0.075)
        anchors.topMargin: 48
        anchors.bottomMargin: 48
        spacing: Math.max(48, parent.width * 0.07)

        ColumnLayout {
            visible: root.width >= 900
            Layout.fillWidth: true
            Layout.maximumWidth: 670
            Layout.alignment: Qt.AlignVCenter
            spacing: 24

            RowLayout {
                spacing: 12
                Image {
                    source: Theme.appLogo
                    sourceSize: Qt.size(56, 56)
                    Layout.preferredWidth: 42
                    Layout.preferredHeight: 42
                    fillMode: Image.PreserveAspectFit
                }
                Text {
                    text: "SERVO"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.6
                }
            }

            Text {
                Layout.fillWidth: true
                text: "Physical AI should improve\nwith evidence, not guesses."
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 32
                font.weight: Font.DemiBold
                lineHeight: 1.1
                wrapMode: Text.WordWrap
            }

            Text {
                Layout.fillWidth: true
                Layout.maximumWidth: 560
                text: "Servo reconstructs test worlds, runs driving policies, diagnoses failures, retrains bounded candidates, and promotes only verified updates."
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: 13
                lineHeight: 1.45
                wrapMode: Text.WordWrap
            }

            ColumnLayout {
                Layout.topMargin: 10
                spacing: 0
                Repeater {
                    model: [
                        { number: "01", title: "Reconstruct", detail: "Turn captured media into an explorable test world" },
                        { number: "02", title: "Run and diagnose", detail: "Collect synchronized failures and causal evidence" },
                        { number: "03", title: "Train and verify", detail: "Protect baselines before any model is promoted" }
                    ]
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredHeight: 61
                        spacing: 14
                        Text {
                            text: modelData.number
                            color: Theme.textMuted
                            font.family: Theme.monoFont
                            font.pixelSize: 9
                        }
                        Rectangle {
                            Layout.preferredWidth: 1
                            Layout.fillHeight: true
                            color: Theme.border
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Text { text: modelData.title; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 11; font.weight: Font.DemiBold }
                            Text { text: modelData.detail; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 10; Layout.fillWidth: true; elide: Text.ElideRight }
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: root.width < 900
            Layout.preferredWidth: 440
            Layout.maximumWidth: 470
            Layout.alignment: Qt.AlignVCenter | Qt.AlignHCenter
            implicitHeight: authContent.implicitHeight + 56
            radius: Theme.cornerPopup
            color: Theme.panel
            border.width: 1
            border.color: Theme.border

            opacity: root.visible ? 1 : 0
            y: root.visible ? 0 : 12
            Behavior on opacity { NumberAnimation { duration: Theme.animSlow; easing.type: Easing.OutCubic } }
            Behavior on y { NumberAnimation { duration: Theme.animMove; easing.type: Easing.OutCubic } }

            ColumnLayout {
                id: authContent
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: 28
                spacing: 15

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Rectangle {
                        Layout.preferredWidth: 34
                        Layout.preferredHeight: 34
                        radius: 9
                        color: Theme.panelRaised
                        SvgIcon {
                            anchors.centerIn: parent
                            source: Theme.icon("verify")
                            iconSize: Theme.iconMd
                            color: Theme.textSecondary
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Text { text: "Operator sign in"; color: Theme.text; font.family: Theme.uiFont; font.pixelSize: 17; font.weight: Font.DemiBold }
                        Text { text: "Protected Google Cloud control plane"; color: Theme.textMuted; font.family: Theme.uiFont; font.pixelSize: 9 }
                    }
                    Rectangle {
                        Layout.preferredWidth: 7
                        Layout.preferredHeight: 7
                        radius: 4
                        color: AuthController.configured ? Theme.success : Theme.warning
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 54
                    radius: Theme.cornerControl
                    color: Theme.tintInfo
                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 9
                        SvgIcon { source: Theme.icon("info"); iconSize: Theme.iconSm; color: Theme.textSecondary }
                        Text {
                            Layout.fillWidth: true
                            text: "Sign in with Google, or use a verified Email/Password account from Firebase Authentication. Servo never receives your Google password."
                            color: Theme.textSecondary
                            font.family: Theme.uiFont
                            font.pixelSize: 9
                            lineHeight: 1.25
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                TextButton {
                    Layout.fillWidth: true
                    text: AuthController.state === "google-browser"
                          ? "Complete sign-in in browser..."
                          : "Continue with Google"
                    tone: "primary"
                    enabled: AuthController.googleSignInAvailable && !AuthController.busy
                    onClicked: {
                        const callbackUrl = AuthController.beginGoogleSignIn()
                        if (callbackUrl.length > 0)
                            Qt.openUrlExternally(callbackUrl)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.borderSoft }
                    Text { text: "OR USE FIREBASE EMAIL"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 8; font.letterSpacing: 0.5 }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.borderSoft }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Text { text: "EMAIL"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 8; font.letterSpacing: 0.7 }
                    TextInput {
                        id: emailField
                        placeholderText: "operator@example.com"
                        enabled: AuthController.configured && !AuthController.busy
                        inputMethodHints: Qt.ImhEmailCharactersOnly | Qt.ImhNoAutoUppercase
                        onAccepted: passwordField.forceActiveFocus()
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Text { text: "FIREBASE PASSWORD"; color: Theme.textMuted; font.family: Theme.monoFont; font.pixelSize: 8; font.letterSpacing: 0.7 }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 7
                        TextInput {
                            id: passwordField
                            placeholderText: "Password"
                            enabled: AuthController.configured && !AuthController.busy
                            echoMode: root.revealPassword ? TextInput.Normal : TextInput.Password
                            onAccepted: root.submit()
                        }
                        TextButton {
                            compact: true
                            text: root.revealPassword ? "Hide" : "Show"
                            enabled: !AuthController.busy
                            onClicked: root.revealPassword = !root.revealPassword
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: errorText.implicitHeight + 18
                    visible: AuthController.lastError.length > 0
                    radius: Theme.cornerControl
                    color: Theme.tintError
                    Text {
                        id: errorText
                        anchors.fill: parent
                        anchors.margins: 9
                        text: AuthController.lastError
                        color: Theme.error
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        wrapMode: Text.WordWrap
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: noticeText.implicitHeight + 18
                    visible: AuthController.notice.length > 0
                    radius: Theme.cornerControl
                    color: Theme.tintSuccess
                    Text {
                        id: noticeText
                        anchors.fill: parent
                        anchors.margins: 9
                        text: AuthController.notice
                        color: Theme.success
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        wrapMode: Text.WordWrap
                    }
                }

                TextButton {
                    Layout.fillWidth: true
                    text: AuthController.busy
                          ? (AuthController.state === "sending-reset" ? "Sending reset email..."
                             : AuthController.state === "sending-verification" ? "Sending verification email..."
                             : "Verifying identity...")
                          : "Continue to Servo"
                    tone: "primary"
                    enabled: AuthController.configured && !AuthController.busy
                             && emailField.text.length > 0 && passwordField.text.length > 0
                    onClicked: root.submit()
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    TextButton {
                        compact: true
                        text: "Reset password"
                        enabled: AuthController.configured && !AuthController.busy && emailField.text.length > 0
                        onClicked: AuthController.requestPasswordReset(emailField.text)
                    }
                    Item { Layout.fillWidth: true }
                    TextButton {
                        compact: true
                        text: "Manage Firebase users"
                        onClicked: Qt.openUrlExternally("https://console.firebase.google.com/project/servo-1f808/authentication/users")
                    }
                }

                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.borderSoft; Layout.topMargin: 2 }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 7
                    SvgIcon { source: Theme.icon("storage"); iconSize: Theme.iconXs; color: Theme.textMuted }
                    Text {
                        Layout.fillWidth: true
                        text: AuthController.projectId.length > 0
                              ? AuthController.projectId + "  ·  Firebase Auth  ·  Cloud Run"
                              : "Firebase configuration required"
                        color: Theme.textMuted
                        font.family: Theme.monoFont
                        font.pixelSize: 8
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }
}
