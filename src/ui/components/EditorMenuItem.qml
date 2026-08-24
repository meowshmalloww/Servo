import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import "."

T.MenuItem {
    id: control

    implicitWidth: 226
    implicitHeight: 32
    leftPadding: 9
    rightPadding: 9
    hoverEnabled: true

    contentItem: RowLayout {
        spacing: 8

        Item {
            Layout.preferredWidth: 15
            Layout.preferredHeight: 15

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
            color: control.enabled ? (control.highlighted ? Theme.accent : Theme.textSecondary) : Theme.textDisabled

            Behavior on color {
                ColorAnimation {
                    duration: Theme.animFast
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: control.text
            color: control.enabled ? Theme.text : Theme.textDisabled
            font.family: Theme.uiFont
            font.pixelSize: 11
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    background: Rectangle {
        radius: Theme.cornerControl - 1
        anchors.fill: parent
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        color: control.highlighted || control.hovered ? Theme.selection : "transparent"

        Behavior on color {
            ColorAnimation {
                duration: Theme.animFast
            }
        }
    }
}
