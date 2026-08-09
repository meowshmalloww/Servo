import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root

    property string title: "Panel"
    property string subtitle: ""
    property string actionGlyph: ""
    property string actionToolTip: ""
    signal actionTriggered

    implicitHeight: Theme.panelHeaderHeight
    color: Theme.chrome
    border.width: 1
    border.color: Theme.border

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 5
        spacing: 8

        Text {
            text: root.title
            color: Theme.text
            font.family: Theme.uiFont
            font.pixelSize: 12
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            Layout.fillWidth: true
        }

        Text {
            visible: root.subtitle.length > 0
            text: root.subtitle
            color: Theme.textMuted
            font.family: Theme.uiFont
            font.pixelSize: 11
            Layout.alignment: Qt.AlignVCenter
        }

        IconButton {
            visible: root.actionGlyph.length > 0
            glyph: root.actionGlyph
            toolTip: root.actionToolTip
            buttonSize: 24
            onClicked: root.actionTriggered()
        }
    }
}
