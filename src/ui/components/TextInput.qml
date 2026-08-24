import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import "."

T.TextField {
    id: control

    // Read-only values render as plain text so inspectors do not look like forms.
    readonly property bool flatField: readOnly

    Layout.fillWidth: true
    implicitHeight: Theme.controlHeight
    implicitWidth: 180
    leftPadding: flatField ? 0 : 10
    rightPadding: flatField ? 0 : 10
    selectByMouse: true
    selectionColor: Theme.selection
    selectedTextColor: Theme.text
    color: control.enabled ? Theme.text : (flatField ? Theme.textMuted : Theme.textDisabled)
    placeholderTextColor: Theme.textDisabled
    font.family: Theme.uiFont
    font.pixelSize: 11
    verticalAlignment: Text.AlignVCenter

    onTextChanged: {
        if (readOnly)
            Qt.callLater(function() { control.cursorPosition = 0; });
    }

    background: Rectangle {
        visible: !control.flatField
        radius: Theme.cornerControl
        color: {
            if (!control.enabled)
                return Theme.panel;
            if (control.activeFocus || control.hovered)
                return Theme.fieldHover;
            return Theme.field;
        }
        border.width: control.activeFocus ? 1 : 0
        border.color: Theme.selectionBorder

        Behavior on color {
            ColorAnimation {
                duration: Theme.animFast
                easing.type: Easing.OutCubic
            }
        }
    }
}
