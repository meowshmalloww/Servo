import QtQuick

Rectangle {
    implicitWidth: 4
    implicitHeight: 4
    color: handleArea.containsMouse ? Theme.selectionBorder : Theme.borderSoft

    MouseArea {
        id: handleArea
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
    }
}
