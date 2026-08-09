import QtQuick
import QtQuick.Templates as T
import "."

T.MenuSeparator {
    implicitWidth: 226
    implicitHeight: 9

    contentItem: Rectangle {
        x: 8
        y: 4
        width: parent.width - 16
        height: 1
        color: Theme.borderSoft
    }
}
