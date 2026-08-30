import QtQuick
import QtQuick.Templates as T
import "."

T.MenuSeparator {
    implicitWidth: 232
    implicitHeight: 10

    contentItem: Rectangle {
        x: 8
        y: 5
        width: parent.width - 16
        height: 1
        color: Theme.borderSoft
        opacity: 0.6
    }
}
