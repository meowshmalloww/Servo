import QtQuick
import QtQuick.Layouts

Item {
    id: root

    property string label: "Property"
    property int labelWidth: 126
    default property alias editor: editorHost.data

    width: parent ? parent.width : implicitWidth
    height: 34

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        spacing: 12

        Text {
            text: root.label
            color: Theme.textSecondary
            font.family: Theme.uiFont
            font.pixelSize: 12
            elide: Text.ElideRight
            Layout.preferredWidth: root.labelWidth
            Layout.alignment: Qt.AlignVCenter
        }

        Item {
            id: editorHost
            implicitHeight: Theme.controlHeight
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
        }
    }
}
