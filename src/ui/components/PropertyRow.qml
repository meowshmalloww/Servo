import QtQuick
import QtQuick.Layouts

Item {
    id: root

    property string label: ""
    property int labelWidth: 132
    default property alias editor: editorHost.data

    width: parent ? parent.width : implicitWidth
    implicitHeight: 36
    height: implicitHeight

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        spacing: 12

        Text {
            text: root.label
            color: Theme.textSecondary
            font.family: Theme.uiFont
            font.pixelSize: 11
            elide: Text.ElideRight
            Layout.preferredWidth: root.labelWidth
            Layout.minimumWidth: 0
            Layout.alignment: Qt.AlignVCenter
        }

        RowLayout {
            id: editorHost
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredHeight: Theme.controlHeight
            Layout.alignment: Qt.AlignVCenter
            spacing: 4
            clip: true
        }
    }
}
