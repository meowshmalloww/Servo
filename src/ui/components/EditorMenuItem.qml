import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import "."

T.MenuItem {
    id: control

    implicitWidth: 226
    implicitHeight: 30
    leftPadding: 9
    rightPadding: 9
    hoverEnabled: true

    contentItem: RowLayout {
        spacing: 7

        Item {
            Layout.preferredWidth: 15
            Layout.preferredHeight: 15

            SvgIcon {
                anchors.centerIn: parent
                visible: control.checkable && control.checked
                source: Theme.icon("check")
                iconSize: 13
            }
        }

        SvgIcon {
            visible: control.icon.source.toString().length > 0
            source: control.icon.source
            iconSize: 14
            opacity: control.enabled ? 1 : 0.4
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
        color: control.highlighted || control.hovered ? Theme.selection : "transparent"
        border.width: control.activeFocus ? 1 : 0
        border.color: Theme.selectionBorder

        Rectangle {
            visible: control.highlighted || control.hovered
            width: 2
            height: parent.height
            color: Theme.selectionBorder
        }
    }
}
