import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import "."

T.MenuItem {
    id: control

    implicitWidth: 232
    implicitHeight: 34
    leftPadding: 9
    rightPadding: 9
    hoverEnabled: true

    contentItem: RowLayout {
        spacing: 9

        Item {
            Layout.preferredWidth: 16
            Layout.preferredHeight: 16

            SvgIcon {
                anchors.centerIn: parent
                visible: control.checkable && control.checked
                source: Theme.icon("check")
                iconSize: Theme.iconSm
                color: Theme.accent
            }
        }

        SvgIcon {
            visible: control.icon.source.toString().length > 0
            source: control.icon.source
            iconSize: Theme.iconSm
            color: control.enabled ? (control.highlighted ? Theme.text : Theme.textSecondary) : Theme.textDisabled

            Behavior on color {
                enabled: Theme.motionEnabled
                ColorAnimation {
                    duration: Theme.animFast
                    easing.type: Easing.OutCubic
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: control.text
            color: control.enabled ? (control.highlighted ? Theme.text : Theme.textSecondary) : Theme.textDisabled
            font.family: Theme.uiFont
            font.pixelSize: 11
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight

            Behavior on color {
                enabled: Theme.motionEnabled
                ColorAnimation {
                    duration: Theme.animFast
                    easing.type: Easing.OutCubic
                }
            }
        }

        Text {
            visible: control.shortcut !== undefined && control.shortcut.toString().length > 0
            text: control.shortcut ? control.shortcut.toString() : ""
            color: Theme.textMuted
            font.family: Theme.monoFont
            font.pixelSize: 9
            Layout.alignment: Qt.AlignVCenter
        }
    }

    background: Rectangle {
        radius: Theme.cornerControl - 1
        anchors.fill: parent
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        color: control.highlighted ? Theme.selection : "transparent"
        border.width: control.highlighted ? 1 : 0
        border.color: Theme.borderSoft

        Behavior on color {
            enabled: Theme.motionEnabled
            ColorAnimation {
                duration: Theme.animFast
                easing.type: Easing.OutCubic
            }
        }
    }
}
