import QtQuick

Rectangle {
    implicitWidth: 4
    implicitHeight: 4
    color: Theme.border

    Rectangle {
        anchors.centerIn: parent
        width: parent.width === 4 ? 1 : parent.width
        height: parent.height === 4 ? 1 : parent.height
        color: Theme.borderStrong
    }
}
