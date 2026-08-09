import QtQuick
import QtQuick.Controls.Basic
import "."

Menu {
    id: control

    implicitWidth: 226
    topPadding: 4
    bottomPadding: 4
    leftPadding: 1
    rightPadding: 1
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

    enter: Transition {}
    exit: Transition {}
}
