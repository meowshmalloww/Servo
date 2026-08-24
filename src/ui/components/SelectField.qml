pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import QtQuick.Templates as T
import "."

T.ComboBox {
    id: control

    property string placeholderText: "Not configured"

    Layout.fillWidth: true
    implicitWidth: 190
    implicitHeight: Theme.controlHeight
    leftPadding: 10
    rightPadding: 28
    currentIndex: -1
    font.family: Theme.uiFont
    font.pixelSize: 11

    contentItem: Text {
        text: control.currentIndex >= 0 ? control.displayText : control.placeholderText
        color: control.currentIndex >= 0 ? Theme.text : Theme.textMuted
        font: control.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: SvgIcon {
        anchors.right: parent.right
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        source: Theme.icon("chevron-down")
        iconSize: Theme.iconSm
        color: control.enabled ? Theme.textMuted : Theme.textDisabled
        rotation: control.popup.visible ? 180 : 0

        Behavior on rotation {
            NumberAnimation {
                duration: Theme.animMove
                easing.type: Easing.OutCubic
            }
        }
    }

    background: Rectangle {
        radius: Theme.cornerControl
        color: {
            if (!control.enabled)
                return Theme.panel;
            if (control.activeFocus || control.hovered || control.popup.visible)
                return Theme.fieldHover;
            return Theme.field;
        }
        border.width: control.activeFocus || control.popup.visible ? 1 : 0
        border.color: Theme.selectionBorder

        Behavior on color {
            ColorAnimation {
                duration: Theme.animFast
                easing.type: Easing.OutCubic
            }
        }
    }

    delegate: T.ItemDelegate {
        id: optionDelegate
        required property int index
        required property var modelData

        width: control.popup.width
        height: 30
        highlighted: control.highlightedIndex === index

        contentItem: Text {
            text: optionDelegate.modelData === undefined ? "" : String(optionDelegate.modelData)
            color: optionDelegate.highlighted ? Theme.accent : Theme.text
            font: control.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight

            Behavior on color {
                ColorAnimation {
                    duration: Theme.animFast
                }
            }
        }

        background: Rectangle {
            radius: Theme.cornerControl - 2
            anchors.fill: parent
            anchors.margins: 3
            color: optionDelegate.highlighted ? Theme.selection : "transparent"

            Behavior on color {
                ColorAnimation {
                    duration: Theme.animFast
                }
            }
        }
    }

    popup: T.Popup {
        y: control.height + 4
        width: control.width
        height: Math.min(contentItem.implicitHeight + 12, 264)
        padding: 4
        closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside

        enter: Transition {
            NumberAnimation {
                property: "opacity"
                from: 0
                to: 1
                duration: Theme.animFast
                easing.type: Easing.OutCubic
            }
            NumberAnimation {
                property: "scale"
                from: 0.96
                to: 1
                duration: Theme.animBase
                easing.type: Easing.OutCubic
            }
        }
        exit: Transition {
            NumberAnimation {
                property: "opacity"
                to: 0
                duration: Theme.animFast
                easing.type: Easing.InCubic
            }
        }

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.delegateModel
            currentIndex: control.highlightedIndex
            boundsBehavior: Flickable.StopAtBounds
            highlightMoveDuration: Theme.animBase
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }
        }

        background: Rectangle {
            radius: Theme.cornerPopup
            color: Theme.panelRaised
            border.width: 1
            border.color: Theme.borderStrong
        }
    }
}
