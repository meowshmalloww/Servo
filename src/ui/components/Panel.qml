import QtQuick

Rectangle {
    id: root

    property real panelRadius: 0

    color: Theme.panel
    radius: panelRadius
    clip: true
}
