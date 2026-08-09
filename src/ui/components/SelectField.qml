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
    Layout.fillHeight: true
    implicitWidth: 190
    implicitHeight: Theme.controlHeight
    leftPadding: 9
    rightPadding: 30
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
        anchors.rightMargin: 7
        anchors.verticalCenter: parent.verticalCenter
        source: Theme.icon("chevron-down")
        iconSize: 13
        opacity: control.enabled ? 0.85 : 0.4
    }

    background: Rectangle {
        radius: Theme.cornerControl
        color: control.enabled ? (control.hovered ? Theme.fieldHover : Theme.field) : Theme.panel
        border.width: 1
        border.color: control.activeFocus || control.popup.visible ? Theme.selectionBorder : Theme.border
    }

    delegate: T.ItemDelegate {
        id: optionDelegate
        required property int index
        required property var modelData

        width: control.popup.width
        height: 29
        highlighted: control.highlightedIndex === index

        contentItem: Text {
            text: optionDelegate.modelData === undefined ? "" : String(optionDelegate.modelData)
            color: Theme.text
            font: control.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        background: Rectangle {
            color: optionDelegate.highlighted ? Theme.selection : "transparent"
            border.width: optionDelegate.highlighted ? 1 : 0
            border.color: Theme.selectionBorder
        }
    }

    popup: T.Popup {
        y: control.height + 2
        width: control.width
        height: Math.min(contentItem.implicitHeight + 2, 260)
        padding: 1
        closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.delegateModel
            currentIndex: control.highlightedIndex
            boundsBehavior: Flickable.StopAtBounds
            highlightMoveDuration: 0
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        }

        background: Rectangle {
            radius: Theme.cornerPopup
            color: Theme.panelRaised
            border.width: 1
            border.color: Theme.borderStrong
        }
    }
}
