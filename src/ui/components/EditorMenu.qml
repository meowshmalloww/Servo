import QtQuick
import QtQuick.Controls.Basic
import "."

Menu {
    id: control

    implicitWidth: 226
    topPadding: 5
    bottomPadding: 5
    leftPadding: 4
    rightPadding: 4
    overlap: 1

    delegate: EditorMenuItem {}

    contentItem: ListView {
        implicitHeight: contentHeight
        model: control.contentModel
        currentIndex: control.currentIndex
        boundsBehavior: Flickable.StopAtBounds
        clip: true
    }

    background: Rectangle {
        color: Theme.panelRaised
        border.width: 1
        border.color: Theme.borderStrong
        radius: Theme.cornerPopup
    }

    enter: Transition {
        NumberAnimation {
            property: "opacity"
            from: 0
            to: 1
            duration: Theme.animFast
            easing.type: Easing.OutCubic
        }
        NumberAnimation {
            property: "scale"
            from: 0.96
            to: 1
            duration: Theme.animBase
            easing.type: Easing.OutCubic
        }
    }

    exit: Transition {
        NumberAnimation {
            property: "opacity"
            to: 0
            duration: Theme.animFast
            easing.type: Easing.InCubic
        }
    }
}
