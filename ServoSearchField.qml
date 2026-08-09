import QtQuick
import QtQuick.Controls.Basic

TextField {
    id: control

    property string hint: qsTr("Search…")

    implicitHeight: Theme.controlHeight
    leftPadding: 28
    rightPadding: 28
    placeholderText: hint
    color: Theme.text
    placeholderTextColor: Theme.textMuted
    selectionColor: Theme.accentDim
    selectedTextColor: Theme.text
    font.family: Theme.uiFont
    font.pixelSize: 12

    background: Rectangle {
        radius: 2
        color: Theme.field
        border.width: 1
        border.color: control.activeFocus ? Theme.accent : (control.hovered ? Theme.borderStrong : Theme.border)

        Text {
            text: "⌕"
            color: Theme.textMuted
            font.family: Theme.uiFont
            font.pixelSize: 15
            anchors.left: parent.left
            anchors.leftMargin: 8
            anchors.verticalCenter: parent.verticalCenter
        }

        Text {
            visible: control.text.length > 0
            text: "×"
            color: clearArea.containsMouse ? Theme.text : Theme.textMuted
            font.family: Theme.uiFont
            font.pixelSize: 13
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter

            MouseArea {
                id: clearArea
                anchors.fill: parent
                anchors.margins: -6
                hoverEnabled: true
                onClicked: control.clear()
            }
        }
    }
}
