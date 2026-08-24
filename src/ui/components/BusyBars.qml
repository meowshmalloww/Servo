pragma ComponentBehavior: Bound

import QtQuick
import "."

Row {
    id: root

    property int barSize: 13
    property color barColor: Theme.accent

    spacing: 3

    Repeater {
        model: 3

        Item {
            id: slot
            required property int index

            width: 3
            height: root.barSize

            Rectangle {
                anchors.fill: parent
                radius: 1.5
                color: root.barColor
                opacity: 0.3

                SequentialAnimation on opacity {
                    running: root.visible && root.opacity > 0 && Theme.motionEnabled
                    loops: Animation.Infinite

                    PauseAnimation {
                        duration: slot.index * 150
                    }
                    NumberAnimation {
                        from: 0.3
                        to: 1
                        duration: 420
                        easing.type: Easing.InOutQuad
                    }
                    NumberAnimation {
                        from: 1
                        to: 0.3
                        duration: 420
                        easing.type: Easing.InOutQuad
                    }
                }
            }
        }
    }
}
