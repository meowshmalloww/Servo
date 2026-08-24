import QtQuick
import QtQuick.Templates as T

T.Button {
    id: control

    property bool current: false

    implicitWidth: Math.max(78, label.implicitWidth + 28)
    implicitHeight: Theme.topBarHeight
    hoverEnabled: true
    font.family: Theme.uiFont

    contentItem: Text {
        id: label
        text: control.text
        color: control.current ? Theme.accent : (control.hovered ? Theme.text : Theme.textMuted)
        font.family: Theme.uiFont
        font.pixelSize: 11
        font.weight: control.current ? Font.DemiBold : Font.Normal
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter

        Behavior on color {
            ColorAnimation {
                duration: Theme.animFast
            }
        }
    }

    background: Item {
        Rectangle {
            anchors.fill: parent
            anchors.margins: 6
            radius: Theme.cornerControl
            color: control.hovered && !control.current ? Theme.panelHover : "transparent"
            opacity: control.hovered && !control.current ? 0.7 : 1

            Behavior on color {
                ColorAnimation {
                    duration: Theme.animFast
                }
            }
        }

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 3
            width: control.current ? Math.min(label.implicitWidth + 8, parent.width - 20) : 0
            height: 2
            radius: 1
            color: Theme.accent

            Behavior on width {
                NumberAnimation {
                    duration: Theme.animMove
                    easing.type: Easing.OutCubic
                }
            }
        }
    }
}
