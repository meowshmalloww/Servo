import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root

    property int currentIndex: 0
    signal requested(int index)
    signal settingsRequested

    color: Theme.chrome
    border.width: 1
    border.color: Theme.border
    implicitWidth: 52

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: 6
        anchors.bottomMargin: 6
        spacing: 2

        Repeater {
            model: [
                { glyph: "▤", tip: "Prepare" },
                { glyph: "▶", tip: "Simulate" },
                { glyph: "⌕", tip: "Diagnose" },
                { glyph: "≋", tip: "Train" },
                { glyph: "✓", tip: "Verify" }
            ]

            delegate: Item {
                required property int index
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredHeight: 48

                Rectangle {
                    anchors.fill: parent
                    anchors.leftMargin: 3
                    anchors.rightMargin: 3
                    radius: 2
                    color: root.currentIndex === index
                           ? Theme.tint(Theme.accent, 0.16)
                           : (area.containsMouse ? Theme.surfaceHover : "transparent")

                    Rectangle {
                        visible: root.currentIndex === index
                        width: 2
                        height: parent.height
                        anchors.left: parent.left
                        color: Theme.accent
                    }
                }

                Text {
                    anchors.centerIn: parent
                    text: modelData.glyph
                    color: root.currentIndex === index ? Theme.accentBright : Theme.textMuted
                    font.family: Theme.uiFont
                    font.pixelSize: 17
                }

                MouseArea {
                    id: area
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.requested(index)
                }

                Rectangle {
                    visible: area.containsMouse
                    x: parent.width + 6
                    anchors.verticalCenter: parent.verticalCenter
                    width: tipText.implicitWidth + 18
                    height: 26
                    radius: 2
                    color: Theme.panelRaised
                    border.width: 1
                    border.color: Theme.borderStrong
                    z: 100

                    Text {
                        id: tipText
                        anchors.centerIn: parent
                        text: modelData.tip
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 48

            Text {
                anchors.centerIn: parent
                text: "⚙"
                color: settingsArea.containsMouse ? Theme.text : Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 16
            }

            MouseArea {
                id: settingsArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.settingsRequested()
            }
        }
    }
}
