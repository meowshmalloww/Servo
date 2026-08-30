import QtQuick
import QtQuick.Controls.Basic
import "."

Menu {
    id: control

    implicitWidth: 240
    topPadding: 6
    bottomPadding: 6
    leftPadding: 4
    rightPadding: 4
    overlap: 2

    delegate: EditorMenuItem {}

    contentItem: ListView {
        implicitHeight: contentHeight
        model: control.contentModel
        currentIndex: control.currentIndex
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        spacing: 1
    }

    background: Rectangle {
        color: Theme.panelRaised
        border.width: 1
        border.color: Theme.borderStrong
        radius: Theme.cornerPopup
    }

    enter: Transition {
        ParallelAnimation {
            NumberAnimation {
                property: "opacity"
                from: 0
                to: 1
                duration: Theme.animFast
                easing.type: Easing.OutCubic
            }
            NumberAnimation {
                property: "y"
                from: 4
                to: 0
                duration: Theme.animMove
                easing.type: Easing.OutCubic
            }
        }
    }

    exit: Transition {
        ParallelAnimation {
            NumberAnimation {
                property: "opacity"
                to: 0
                duration: Theme.animFast
                easing.type: Easing.InCubic
            }
            NumberAnimation {
                property: "y"
                to: 3
                duration: Theme.animFast
                easing.type: Easing.InCubic
            }
        }
    }
}
