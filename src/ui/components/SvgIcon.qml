import QtQuick
import QtQuick.Window

Image {
    id: root

    property int iconSize: 16

    width: iconSize
    height: iconSize
    sourceSize.width: iconSize * Screen.devicePixelRatio
    sourceSize.height: iconSize * Screen.devicePixelRatio
    fillMode: Image.PreserveAspectFit
    asynchronous: false
    cache: true
    smooth: true
    mipmap: false
}
