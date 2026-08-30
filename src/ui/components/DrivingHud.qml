import QtQuick
import QtQuick.Layouts
import "."

Rectangle {
    id: root

    color: Theme.overlayHud
    radius: Theme.cornerPopup
    implicitHeight: 76
    implicitWidth: metrics.implicitWidth + 28

    GridLayout {
        id: metrics
        anchors.fill: parent
        anchors.margins: 10
        columns: 5
        columnSpacing: 16
        rowSpacing: 5

        MetricReadout { label: "SPEED"; value: (NativeVehicleController.speedMps * 3.6).toFixed(1) + " km/h" }
        MetricReadout { label: "STEER"; value: NativeVehicleController.steering.toFixed(3) }
        MetricReadout { label: "THROTTLE"; value: NativeVehicleController.throttle.toFixed(2) }
        MetricReadout { label: "BRAKE"; value: NativeVehicleController.brake.toFixed(2) }
        MetricReadout { label: "CONTACT"; value: NativeVehicleController.wheelContacts + "/4 wheels" }
        MetricReadout { label: "FRAME"; value: String(NativeVehicleController.frameId) }
        MetricReadout { label: "ROUTE"; value: (NativeVehicleController.routeCompletion * 100).toFixed(1) + "%" }
        MetricReadout { label: "LATERAL"; value: NativeVehicleController.lateralErrorM.toFixed(2) + " m" }
        MetricReadout { label: "GRAVITY"; value: NativeVehicleController.gravityMetersPerSecondSquared.toFixed(5) + " m/s²" }
        MetricReadout { label: "SURFACE"; value: NativeVehicleController.grounded ? "ROAD" : "VOID / AIR" }
    }
}
