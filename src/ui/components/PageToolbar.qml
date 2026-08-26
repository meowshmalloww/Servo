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

    // Every page inherits a help affordance: the "?" button appears when a
    // help text is provided (or falls back to the subtitle), opening a small
    // explanation card.  Zero per-page edits required.
    readonly property string effectiveHelp: helpText.length > 0 ? helpText : subtitle
    readonly property Item windowOverlay: root.Overlay.overlay

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 10
        spacing: 10

        SvgIcon {
            visible: root.iconSource.toString().length > 0
            source: root.iconSource
            iconSize: Theme.iconMd
            color: Theme.accent
        }

        Text {
            text: root.title
            color: Theme.text
            font.family: Theme.uiFont
            font.pixelSize: 13
            font.weight: Font.DemiBold
            font.letterSpacing: 0.2
        }

        Text {
            visible: root.subtitle.length > 0
            text: root.subtitle
            color: Theme.textMuted
            font.family: Theme.uiFont
            font.pixelSize: 10
            elide: Text.ElideRight
            Layout.maximumWidth: 560
            Layout.leftMargin: root.subtitle.length > 0 ? 2 : 0
        }

        Item {
            Layout.fillWidth: true
        }

        RowLayout {
            id: actionRow
            spacing: 6
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
        x: Math.max(12, root.width - width - 16)
        y: root.height + 8
        width: Math.min(460, (root.windowOverlay ? root.windowOverlay.width : 800) - 32)
        padding: 14
        modal: false
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            radius: Theme.cornerCard
            color: Theme.panelRaised
            border.color: Theme.border
        }

        contentItem: ColumnLayout {
            spacing: 8

            RowLayout {
                spacing: 8

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
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
    }
}
