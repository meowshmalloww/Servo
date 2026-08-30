import QtQuick
import QtQuick.Layouts
import "."

Rectangle {
    id: root

    implicitWidth: 280
    implicitHeight: 190
    color: Theme.overlayHud
    radius: Theme.cornerPopup
    border.width: 1
    border.color: Theme.borderStrong

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 6

        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: "EXACT POLICY INPUT"
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: 9
                font.weight: Font.DemiBold
                font.letterSpacing: 0.7
            }
            StatusBadge {
                text: SimulationController.observationSource.length > 0
                      ? SimulationController.observationSource : "No frame"
                tone: SimulationController.policyFrameRevision > 0 ? "info" : "neutral"
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "black"
            clip: true
            Image {
                anchors.fill: parent
                source: SimulationController.policyFrameUrl
                fillMode: Image.PreserveAspectFit
                cache: false
                asynchronous: true
            }
            Text {
                anchors.centerIn: parent
                visible: SimulationController.policyFrameRevision === 0
                text: "Waiting for synchronized policy frame"
                color: Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 9
            }
        }
        Text {
            Layout.fillWidth: true
            text: "Frame " + SimulationController.policyFrameId
                  + " · preview identity follows backend frame"
            color: Theme.textMuted
            font.family: Theme.monoFont
            font.pixelSize: 8
            elide: Text.ElideRight
        }
    }
}
