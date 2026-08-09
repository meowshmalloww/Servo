import QtQuick
import QtQuick.Templates as T

T.Button {
    id: control

    property bool current: false

    implicitWidth: Math.max(78, label.implicitWidth + 28)
    implicitHeight: Theme.topBarHeight
    hoverEnabled: true

    contentItem: Text {
        id: label
        text: control.text
        color: control.current ? Theme.text : (control.hovered ? Theme.textSecondary : Theme.textMuted)
        font.family: Theme.uiFont
        font.pixelSize: 11
        font.weight: control.current ? Font.DemiBold : Font.Normal
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }

    background: Item {
        Rectangle {
            visible: control.hovered && !control.current
            anchors.fill: parent
            color: Theme.panelHover
            opacity: 0.45
        }

        Rectangle {
            visible: control.current
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            height: 2
            color: Theme.accent
        }
    }
}
