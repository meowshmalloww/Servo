import QtQuick
import QtQuick.Effects
import "."

Item {
    id: root

    property int iconSize: Theme.iconMd
    property url source
    property color color: Theme.iconDefault
    property bool tinted: source.toString().indexOf("/icons/") >= 0

    implicitWidth: iconSize
    implicitHeight: iconSize

    Image {
        id: glyph
        anchors.centerIn: parent
        width: root.iconSize
        height: root.iconSize
        sourceSize.width: Math.ceil(root.iconSize * 2)
        sourceSize.height: Math.ceil(root.iconSize * 2)
        fillMode: Image.PreserveAspectFit
        asynchronous: false
        cache: true
        smooth: true
        mipmap: false
        visible: false
        source: root.source
    }

    MultiEffect {
        anchors.fill: glyph
        source: glyph
        autoPaddingEnabled: false
        brightness: 0.0
        contrast: 0.0
        saturation: 0.0
        colorization: root.tinted ? 1.0 : 0.0
        colorizationColor: root.color
    }
}
