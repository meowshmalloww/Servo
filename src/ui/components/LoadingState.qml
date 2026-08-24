pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "."

RowLayout {
    id: root

    property string label: "Working"
    property string variant: "Drive"
    property bool running: true
    property bool showElapsed: true
    property double startedAt: 0
    property double currentTime: 0

    readonly property int cycleDuration: variant === "Orbit" ? 950 : 650
    readonly property int pulseDuration: variant === "Orbit" ? 70 : 150

    function cellDelay(index) {
        if (variant === "Orbit") {
            const order = [0, 1, 2, 5, 8, 7, 6, 3];
            const position = order.indexOf(index);
            return position < 0 ? -1 : position * 110;
        }
        const row = Math.floor(index / 3);
        const column = index % 3;
        return (column + Math.abs(row - 1)) * 90;
    }

    function elapsedText() {
        const seconds = Math.max(0, currentTime - startedAt) / 1000;
        if (seconds < 60)
            return seconds.toFixed(1) + "s";
        return Math.floor(seconds / 60) + "m " + (seconds % 60).toFixed(1) + "s";
    }

    visible: running
    opacity: running ? 1 : 0
    spacing: 9
    Accessible.name: label + (showElapsed ? " " + elapsedText() : "")

    onRunningChanged: {
        if (running) {
            startedAt = Date.now();
            currentTime = startedAt;
        }
    }

    Component.onCompleted: {
        if (running) {
            startedAt = Date.now();
            currentTime = startedAt;
        }
    }

    Grid {
        Layout.preferredWidth: 15
        Layout.preferredHeight: 15
        Layout.alignment: Qt.AlignVCenter
        columns: 3
        rows: 3
        spacing: 1.5

        Repeater {
            model: 9

            Rectangle {
                id: cell
                required property int index
                readonly property int delay: root.cellDelay(index)

                width: 4
                height: 4
                radius: root.variant === "Dots" ? 2 : 1
                color: Theme.accent
                opacity: delay < 0 ? 0.07 : 0.15

                SequentialAnimation on opacity {
                    running: root.running && root.visible && Theme.motionEnabled && cell.delay >= 0
                    loops: Animation.Infinite

                    PauseAnimation {
                        duration: Math.max(0, cell.delay)
                    }
                    NumberAnimation {
                        from: 0.15
                        to: 1
                        duration: root.pulseDuration
                        easing.type: Easing.InOutQuad
                    }
                    NumberAnimation {
                        from: 1
                        to: 0.15
                        duration: root.pulseDuration
                        easing.type: Easing.InOutQuad
                    }
                    PauseAnimation {
                        duration: Math.max(0, root.cycleDuration - cell.delay - root.pulseDuration * 2)
                    }
                }
            }
        }
    }

    Text {
        text: root.label
        color: Theme.textSecondary
        font.family: Theme.uiFont
        font.pixelSize: 11
        font.weight: Font.DemiBold
        verticalAlignment: Text.AlignVCenter
    }

    Text {
        visible: root.showElapsed
        text: root.elapsedText()
        color: Theme.textMuted
        font.family: Theme.monoFont
        font.pixelSize: 10
        font.features: {"tnum": 1}
        verticalAlignment: Text.AlignVCenter
    }

    Timer {
        interval: 100
        repeat: true
        running: root.running && root.visible
        onTriggered: root.currentTime = Date.now()
    }

    Behavior on opacity {
        enabled: Theme.motionEnabled
        NumberAnimation {
            duration: Theme.animBase
            easing.type: Easing.OutCubic
        }
    }
}
