import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "."

Rectangle {
    id: root

    property string title: ""
    property string subtitle: ""
    property url iconSource: ""
    property string helpText: ""
    default property alias actions: actionRow.data

    implicitHeight: Theme.toolbarHeight
    color: Theme.chrome

    readonly property string effectiveHelp: helpText.length > 0 ? helpText : subtitle
    readonly property Item windowOverlay: root.Overlay.overlay

    // Bottom hairline for page separation
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: Theme.borderSoft
        opacity: 0.6
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 8
        spacing: 10

        SvgIcon {
            visible: root.iconSource.toString().length > 0
            source: root.iconSource
            iconSize: Theme.iconMd
            color: Theme.accentDim
        }

        Text {
            id: titleLabel
            text: root.title
            color: Theme.text
            font.family: Theme.uiFont
            font.pixelSize: 13
            font.weight: Font.DemiBold
            font.letterSpacing: 0.15
            Layout.alignment: Qt.AlignVCenter
        }

        Text {
            id: subtitleLabel
            visible: root.subtitle.length > 0
            text: root.subtitle
            color: Theme.textMuted
            font.family: Theme.uiFont
            font.pixelSize: 10
            elide: Text.ElideRight
            Layout.maximumWidth: Math.max(120, Math.min(520, root.width - titleLabel.implicitWidth - actionRow.implicitWidth - 120))
            Layout.alignment: Qt.AlignVCenter
            Layout.leftMargin: 2
        }

        Item {
            Layout.fillWidth: true
        }

        RowLayout {
            id: actionRow
            spacing: 6
            Layout.alignment: Qt.AlignVCenter
        }

        IconButton {
            id: helpButton
            visible: root.effectiveHelp.length > 0
            iconSource: Theme.icon("info")
            toolTip: "What is this page?"
            buttonSize: 26
            onClicked: helpPopup.opened ? helpPopup.close() : helpPopup.open()
        }
    }

    Popup {
        id: helpPopup
        parent: root.windowOverlay ? root.windowOverlay : root
        x: Math.max(12, Math.min(root.width - width - 12, root.width - width - 12))
        y: root.height + 6
        width: Math.min(440, (root.windowOverlay ? root.windowOverlay.width : 960) - 24)
        padding: 14
        modal: false
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        enter: Transition {
            ParallelAnimation {
                NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.animFast; easing.type: Easing.OutCubic }
                NumberAnimation { property: "y"; from: 4; to: 0; duration: Theme.animMove; easing.type: Easing.OutCubic }
            }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; to: 0; duration: Theme.animFast; easing.type: Easing.InCubic }
        }

        background: Rectangle {
            radius: Theme.cornerCard
            color: Theme.panelRaised
            border.width: 1
            border.color: Theme.borderStrong
        }

        contentItem: ColumnLayout {
            spacing: 9

            RowLayout {
                spacing: 9

                SvgIcon {
                    source: root.iconSource
                    iconSize: Theme.iconSm
                    color: Theme.accentDim
                    Layout.alignment: Qt.AlignVCenter
                }
                Text {
                    text: root.title
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
                IconButton {
                    iconSource: Theme.icon("close")
                    toolTip: "Close"
                    buttonSize: 22
                    onClicked: helpPopup.close()
                }
            }

            Text {
                text: root.effectiveHelp
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: 11
                lineHeight: 1.35
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
    }
}
