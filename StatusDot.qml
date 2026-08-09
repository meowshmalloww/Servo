import QtQuick

Item {
    id: root

    property color dotColor: Theme.green
    property bool pulse: false

    implicitWidth: 10
    implicitHeight: 10

    Rectangle {
        anchors.centerIn: parent
        width: 7
        height: 7
        radius: 4
        color: parent.dotColor

        SequentialAnimation on opacity {
            running: root.pulse
            loops: Animation.Infinite
            NumberAnimation { from: 1.0; to: 0.35; duration: 650 }
            NumberAnimation { from: 0.35; to: 1.0; duration: 650 }
        }
    }
}
