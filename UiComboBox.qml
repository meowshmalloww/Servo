import QtQuick
import QtQuick.Controls.Basic

ComboBox {
    id: control

    anchors.fill: parent
    implicitHeight: Theme.controlHeight
    leftPadding: 9
    rightPadding: 28
    hoverEnabled: true
    font.family: Theme.uiFont
    font.pixelSize: 12

    contentItem: Text {
        text: control.displayText
        color: control.enabled ? Theme.text : Theme.textDisabled
        font: control.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Text {
        x: control.width - width - 9
        y: (control.height - height) / 2
        text: "⌄"
        color: Theme.textMuted
        font.family: Theme.uiFont
        font.pixelSize: 12
    }

    background: Rectangle {
        radius: 2
        color: Theme.field
        border.width: 1
        border.color: control.activeFocus ? Theme.accent : (control.hovered ? Theme.borderStrong : Theme.border)
    }

    delegate: ItemDelegate {
        width: control.width
        height: Theme.controlHeight
        highlighted: control.highlightedIndex === index

        contentItem: Text {
            text: modelData
            color: highlighted ? Theme.text : Theme.textSecondary
            font.family: Theme.uiFont
            font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter
        }

        background: Rectangle {
            color: highlighted ? Theme.surfaceHover : Theme.panelRaised
        }
    }

    popup: Popup {
        y: control.height + 2
        width: control.width
        implicitHeight: contentItem.implicitHeight + 2
        padding: 1

        contentItem: ListView {
            clip: true
            implicitHeight: Math.min(contentHeight, 220)
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator { }
        }

        background: Rectangle {
            color: Theme.panelRaised
            border.width: 1
            border.color: Theme.borderStrong
        }
    }
}
