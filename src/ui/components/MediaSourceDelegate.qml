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
        if (probeStatus === "ready") return "success";
        if (probeStatus === "error" || probeStatus === "missing") return "error";
        return "info";
    }

    function technicalSummary() {
        const values = [];
        if (dimensionsText !== "—") values.push(dimensionsText);
        if (mediaKind === "video" && framesPerSecondText !== "—")
            values.push(framesPerSecondText);
        if (mediaKind === "video" && durationText !== "—")
            values.push(durationText);
        if (codecName.length > 0) values.push(codecName.toUpperCase());
        if (pixelFormat.length > 0) values.push(pixelFormat);
        if (rotationDegrees !== 0) values.push(rotationDegrees + "° rotation");
        return values.length > 0 ? values.join("  ·  ") : "Waiting for source metadata";
    }

    implicitHeight: probeError.length > 0 ? 106 : 82
    color: rowMouse.containsMouse ? Theme.panelHover : "transparent"
    border.width: 0

    MouseArea {
        id: rowMouse
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: Theme.borderSoft
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
            border.width: 1
            border.color: Theme.border
            radius: Theme.cornerControl

            SvgIcon {
                anchors.centerIn: parent
                source: Theme.icon(root.mediaKind === "video" ? "camera" : "file")
                iconSize: 17
                opacity: 0.85
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
                    font.pixelSize: 8
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
                font.pixelSize: 8
                elide: Text.ElideRight
            }

            Text {
                Layout.fillWidth: true
                text: root.sourcePath
                color: Theme.textMuted
                font.family: Theme.monoFont
                font.pixelSize: 8
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
            spacing: 4

            IconButton {
                visible: root.probeStatus === "error" || root.probeStatus === "missing"
                iconSource: Theme.icon("refresh")
                toolTip: "Retry metadata probe"
                buttonSize: 25
                onClicked: root.retryRequested(root.index)
            }

            IconButton {
                iconSource: Theme.icon("close")
                toolTip: "Remove reference (source file is not deleted)"
                buttonSize: 25
                onClicked: root.removeRequested(root.index)
            }
        }
    }
}
