import QtQuick
import QtQuick.Layouts
import "."

Rectangle {
    id: root

    required property int index
    required property string sourceName
    required property string sourcePath
    required property string mediaKind
    required property string probeStatus
    required property string probeStatusText
    required property string sizeText
    required property string dimensionsText
    required property string durationText
    required property string framesPerSecondText
    required property string codecName
    required property string containerName
    required property string pixelFormat
    required property string colorDescription
    required property int rotationDegrees
    required property string fingerprint
    required property string probeError

    signal retryRequested(int row)
    signal removeRequested(int row)

    function statusTone() {
        if (probeStatus === "ready")
            return "success";
        if (probeStatus === "error" || probeStatus === "missing")
            return "error";
        return "info";
    }

    function technicalSummary() {
        const values = [];
        if (dimensionsText !== "—")
            values.push(dimensionsText);
        if (mediaKind === "video" && framesPerSecondText !== "—")
            values.push(framesPerSecondText);
        if (mediaKind === "video" && durationText !== "—")
            values.push(durationText);
        if (codecName.length > 0)
            values.push(codecName.toUpperCase());
        if (pixelFormat.length > 0)
            values.push(pixelFormat);
        if (rotationDegrees !== 0)
            values.push(rotationDegrees + "° rotation");
        return values.length > 0 ? values.join("  ·  ") : "Waiting for source metadata";
    }

    implicitHeight: probeError.length > 0 ? 104 : 80
    radius: Theme.cornerCard - 3
    color: rowMouse.containsMouse ? Theme.panelRaised : "transparent"

    Behavior on color {
        ColorAnimation {
            duration: Theme.animFast
            easing.type: Easing.OutCubic
        }
    }

    MouseArea {
        id: rowMouse
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 6
        anchors.topMargin: 8
        anchors.bottomMargin: 8
        spacing: 10

        Rectangle {
            Layout.preferredWidth: 34
            Layout.preferredHeight: 34
            Layout.alignment: Qt.AlignTop
            color: Theme.field
            radius: Theme.cornerTile

            SvgIcon {
                anchors.centerIn: parent
                source: Theme.icon(root.mediaKind === "video" ? "camera" : "file")
                iconSize: 15
                color: Theme.textMuted
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 3

            RowLayout {
                Layout.fillWidth: true
                spacing: 7

                Text {
                    Layout.fillWidth: true
                    text: root.sourceName
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    elide: Text.ElideMiddle
                }

                Text {
                    text: root.sizeText
                    color: Theme.textMuted
                    font.family: Theme.monoFont
                    font.pixelSize: 9
                }

                StatusBadge {
                    text: root.probeStatusText
                    tone: root.statusTone()
                }
            }

            Text {
                Layout.fillWidth: true
                text: root.technicalSummary()
                color: Theme.textSecondary
                font.family: Theme.monoFont
                font.pixelSize: 9
                elide: Text.ElideRight
            }

            Text {
                Layout.fillWidth: true
                text: root.sourcePath
                color: Theme.textMuted
                font.family: Theme.monoFont
                font.pixelSize: 9
                elide: Text.ElideMiddle
            }

            Text {
                Layout.fillWidth: true
                visible: root.probeError.length > 0
                text: root.probeError
                color: Theme.error
                font.family: Theme.uiFont
                font.pixelSize: 9
                elide: Text.ElideRight
            }
        }

        ColumnLayout {
            Layout.alignment: Qt.AlignTop
            spacing: 2

            IconButton {
                visible: root.probeStatus === "error" || root.probeStatus === "missing"
                iconSource: Theme.icon("refresh")
                toolTip: "Retry metadata probe"
                buttonSize: 24
                onClicked: root.retryRequested(root.index)
            }

            IconButton {
                iconSource: Theme.icon("close")
                toolTip: "Remove reference (source file is not deleted)"
                buttonSize: 24
                onClicked: root.removeRequested(root.index)
            }
        }
    }
}
