import QtQuick

Image {
    id: root

    property int iconSize: 16

    width: iconSize
    height: iconSize
    sourceSize.width: iconSize
    sourceSize.height: iconSize
    fillMode: Image.PreserveAspectFit
    asynchronous: false
    cache: true
    smooth: true
    mipmap: false
}
