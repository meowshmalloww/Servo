import QtQuick
import QtQuick.Layouts
import "."

ColumnLayout {
    id: root

    property bool worldPublished: false
    property bool appearanceAvailable: false
    property string scaleStatus: "unknown"
    property bool executionBundleAvailable: false
    property bool executionReady: false
    signal prepareRequested()

    spacing: 2

    readonly property bool runtimeReady: SimulationController.carlaRuntimeState === "ready"

    PropertyRow {
        label: "Runtime"
        labelWidth: 92
        StatusBadge {
            text: SimulationController.carlaRuntimeState
            tone: root.runtimeReady ? "success"
                  : SimulationController.carlaRuntimeState === "runtime-missing" ? "error" : "warning"
        }
    }
    PropertyRow {
        label: "CARLA"
        labelWidth: 92
        Text {
            text: SimulationController.carlaVersion.length > 0
                  ? SimulationController.carlaVersion : "Expected 0.9.16"
            color: Theme.text
            font.family: Theme.monoFont
            font.pixelSize: 10
        }
    }
    PropertyRow {
        label: "Package"
        labelWidth: 92
        Text {
            Layout.fillWidth: true
            text: SimulationController.carlaRuntimeRoot.length > 0
                  ? SimulationController.carlaRuntimeRoot : "Not registered"
            color: Theme.textMuted
            elide: Text.ElideMiddle
            font.family: Theme.monoFont
            font.pixelSize: 10
        }
    }
    PropertyRow {
        label: "Integration"
        labelWidth: 92
        StatusBadge {
            text: SimulationController.carlaPreflightState
            tone: SimulationController.carlaPreflightState === "verified" ? "success"
                  : SimulationController.carlaPreflightState === "failed" ? "error" : "warning"
        }
    }
    PropertyRow {
        label: "Real test"
        labelWidth: 92
        Text {
            text: SimulationController.carlaPreflightState === "verified"
                  ? SimulationController.carlaPhysicalDisplacementM.toFixed(2) + " m · "
                    + SimulationController.carlaSensorFrameBytes + " RGB bytes"
                  : "Physics + RGB not yet run"
            color: Theme.text
            font.family: Theme.monoFont
            font.pixelSize: 10
        }
    }
    PropertyRow {
        label: "Appearance"
        labelWidth: 92
        StatusBadge { text: root.appearanceAvailable ? "Servo 3DGS" : "Missing"; tone: root.appearanceAvailable ? "success" : "error" }
    }
    PropertyRow {
        label: "Scale"
        labelWidth: 92
        StatusBadge {
            text: root.scaleStatus
            tone: root.scaleStatus === "metric" || root.scaleStatus === "measured"
                  || root.scaleStatus === "inferred" ? "success" : "warning"
        }
    }
    PropertyRow {
        label: "OpenDRIVE"
        labelWidth: 92
        StatusBadge { text: root.executionBundleAvailable ? "Generated" : "Not generated"; tone: root.executionBundleAvailable ? "info" : "warning" }
    }
    PropertyRow {
        label: "Physics"
        labelWidth: 92
        StatusBadge { text: root.executionReady ? "Ready" : "Blocked"; tone: root.executionReady ? "success" : "warning" }
    }
    Item {
        Layout.fillWidth: true
        Layout.preferredHeight: 76
        TextButton {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 10
            text: "Verify CARLA physics + RGB"
            iconSource: Theme.icon("check")
            enabled: root.runtimeReady && !SimulationController.busy
            onClicked: SimulationController.verifyCarlaIntegration()
        }
        TextButton {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 10
            text: "Prepare for CARLA"
            iconSource: Theme.icon("build")
            enabled: root.worldPublished && root.appearanceAvailable && !SimulationController.busy
            onClicked: root.prepareRequested()
        }
    }
}
