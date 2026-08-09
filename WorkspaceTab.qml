import QtQuick
import QtQuick.Controls.Basic

AbstractButton {
    id: control

    property bool current: false
    hoverEnabled: true
    implicitWidth: 108
    implicitHeight: Theme.toolbarHeight

    contentItem: Text {
        text: control.text
        color: control.current ? Theme.text : (control.hovered ? Theme.textSecondary : Theme.textMuted)
        font.family: Theme.uiFont
        font.pixelSize: 13
        font.weight: control.current ? Font.DemiBold : Font.Normal
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }

    background: Rectangle {
        color: control.hovered && !control.current ? Theme.tint(Theme.text, 0.025) : "transparent"

        Rectangle {
            width: parent.width
            height: 2
            anchors.bottom: parent.bottom
            color: Theme.accent
            visible: control.current
        }
    }
}
