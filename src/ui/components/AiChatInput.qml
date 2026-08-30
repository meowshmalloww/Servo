pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import QtQuick.Shapes
import "."

Rectangle {
    id: root

    property var modelOptions: []
    property var efforts: []
    property var attachments: []
    property int maxAttachments: 6
    property bool busy: false
    property string busyLabel: "Thinking"
    property string busyVariant: "Dots"
    property bool backendConfigured: false
    readonly property var selectedOption: root.modelOptions.length > modelPill.selectedIndex
                                           ? root.modelOptions[modelPill.selectedIndex]
                                           : ({ "name": "", "description": "", "fixedHigh": false })
    readonly property bool fixedHighThinking: Boolean(root.selectedOption.fixedHigh)
    readonly property string selectedModel: String(root.selectedOption.name)
    readonly property var availableEfforts: root.selectedOption.efforts !== undefined
                                            ? root.selectedOption.efforts
                                            : root.efforts
    readonly property string selectedEffort: root.fixedHighThinking
                                              ? "High"
                                              : (root.availableEfforts.length > 0
                                                 ? String(root.availableEfforts[effortCycler.index])
                                                 : "Medium")
    property real highChargeProgress: 0
    property real highChargeOpacity: 0
    property real highChargeImpact: 0
    readonly property bool highChargeActive: root.highChargeOpacity > 0.01

    signal sendRequested(string prompt, string modelName, string effortName)
    signal stopRequested()
    signal attachRequested()
    signal removeAttachmentRequested(int index)

    function clearPrompt() {
        promptArea.text = "";
    }

    function trySubmit() {
        if (busy) {
            stopRequested();
            return;
        }
        const prompt = promptArea.text.trim();
        if (prompt.length === 0 || !backendConfigured)
            return;
        sendRequested(prompt, selectedModel, selectedEffort);
    }

    function triggerHighCharge() {
        if (!Theme.motionEnabled)
            return;
        highCharge.restart();
    }

    function effortIndex(efforts, value) {
        for (let index = 0; index < efforts.length; ++index) {
            if (String(efforts[index]) === value)
                return index;
        }
        return -1;
    }

    function effortIntensity(value) {
        const index = root.effortIndex(["Low", "Medium", "High", "XHigh", "Max"], value);
        return index < 0 ? 2 : index + 1;
    }

    function selectModel(index) {
        if (index < 0 || index >= root.modelOptions.length)
            return;
        const previousEffort = root.selectedEffort;
        const option = root.modelOptions[index];
        modelPill.selectedIndex = index;
        const optionEfforts = option.efforts !== undefined ? option.efforts : root.efforts;
        let nextIndex = Boolean(option.fixedHigh)
                        ? root.effortIndex(optionEfforts, "High")
                        : root.effortIndex(optionEfforts, previousEffort);
        if (nextIndex < 0)
            nextIndex = Math.max(0, root.effortIndex(optionEfforts, "Medium"));
        effortCycler.index = nextIndex;
        if (root.selectedEffort === "High")
            root.triggerHighCharge();
        modelPopup.close();
    }

    function cycleEffort() {
        if (root.fixedHighThinking || root.availableEfforts.length === 0)
            return;
        const nextIndex = (effortCycler.index + 1) % root.availableEfforts.length;
        effortCycler.index = nextIndex;
        if (String(root.availableEfforts[nextIndex]) === "High")
            root.triggerHighCharge();
    }

    implicitWidth: 720
    implicitHeight: composerLayout.implicitHeight + 20
    radius: 18
    color: Theme.panelRaised
    border.width: promptArea.activeFocus ? 1 : 0
    border.color: Theme.selectionBorder

    Behavior on implicitHeight {
        enabled: Theme.motionEnabled
        NumberAnimation {
            duration: Theme.animMove
            easing.type: Easing.OutCubic
        }
    }

    ColumnLayout {
        id: composerLayout
        anchors.fill: parent
        anchors.margins: 10
        spacing: 7

        Flickable {
            visible: root.attachments.length > 0
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 48 : 0
            contentWidth: attachmentRow.implicitWidth
            contentHeight: height
            flickableDirection: Flickable.HorizontalFlick
            boundsBehavior: Flickable.StopAtBounds
            clip: true

            Row {
                id: attachmentRow
                height: parent.height
                spacing: 7

                Repeater {
                    model: root.attachments

                    Rectangle {
                        id: attachmentChip
                        required property int index
                        required property var modelData

                        width: Math.min(188, chipRow.implicitWidth + 14)
                        height: 44
                        radius: Theme.cornerCard - 2
                        color: Theme.field

                        RowLayout {
                            id: chipRow
                            anchors.fill: parent
                            anchors.leftMargin: 4
                            anchors.rightMargin: 3
                            spacing: 6

                            Image {
                                Layout.preferredWidth: 36
                                Layout.preferredHeight: 36
                                source: attachmentChip.modelData.url
                                sourceSize: Qt.size(48, 48)
                                asynchronous: true
                                fillMode: Image.PreserveAspectCrop
                            }

                            Text {
                                Layout.fillWidth: true
                                Layout.maximumWidth: 105
                                text: String(attachmentChip.modelData.name)
                                color: Theme.textSecondary
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                                elide: Text.ElideMiddle
                            }

                            IconButton {
                                iconSource: Theme.icon("close")
                                toolTip: "Remove attachment"
                                buttonSize: 24
                                onClicked: root.removeAttachmentRequested(attachmentChip.index)
                            }
                        }

                        NumberAnimation on opacity {
                            from: 0
                            to: 1
                            duration: Theme.animBase
                            running: Theme.motionEnabled
                        }
                    }
                }
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(58, Math.min(150, promptArea.contentHeight + 22))
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.policy: promptArea.contentHeight > 128
                                       ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff

            TextArea {
                id: promptArea
                Accessible.name: "Message Servo"
                placeholderText: root.backendConfigured
                                 ? "Message Servo"
                                 : "Connect Gemini in Settings"
                enabled: !root.busy
                wrapMode: TextArea.Wrap
                selectByMouse: true
                leftPadding: 4
                rightPadding: 4
                topPadding: 5
                bottomPadding: 5
                color: Theme.text
                placeholderTextColor: Theme.textMuted
                selectionColor: Theme.selection
                selectedTextColor: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 12
                background: null

                Keys.onReturnPressed: event => {
                    if (!(event.modifiers & Qt.ShiftModifier)) {
                        root.trySubmit();
                        event.accepted = true;
                    }
                }
                Keys.onEnterPressed: event => {
                    if (!(event.modifiers & Qt.ShiftModifier)) {
                        root.trySubmit();
                        event.accepted = true;
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Rectangle {
                id: modelPill
                property int selectedIndex: 0
                Layout.preferredWidth: Math.min(210, pillRow.implicitWidth + 20)
                Layout.preferredHeight: 30
                radius: 15
                color: modelPopup.opened || pillClick.containsMouse
                       ? Theme.selection : "transparent"
                enabled: !root.busy && root.modelOptions.length > 0

                Behavior on color {
                    ColorAnimation { duration: Theme.animFast }
                }

                MouseArea {
                    id: pillClick
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    hoverEnabled: true
                    onClicked: modelPopup.opened ? modelPopup.close() : modelPopup.open()
                }

                Row {
                    id: pillRow
                    anchors.centerIn: parent
                    spacing: 6

                    SvgIcon {
                        source: Theme.icon("sparkle")
                        iconSize: 12
                        color: modelPopup.opened || pillClick.containsMouse
                               ? Theme.text : Theme.textSecondary
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Text {
                        id: modelPillLabel
                        text: root.selectedModel
                        color: modelPopup.opened || pillClick.containsMouse
                               ? Theme.text : Theme.textSecondary
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter

                        onTextChanged: if (Theme.motionEnabled) selectionPulse.restart()
                        SequentialAnimation {
                            id: selectionPulse
                            NumberAnimation {
                                target: modelPillLabel
                                property: "scale"
                                from: 0.94
                                to: 1.04
                                duration: Theme.animFast
                                easing.type: Easing.OutCubic
                            }
                            NumberAnimation {
                                target: modelPillLabel
                                property: "scale"
                                to: 1
                                duration: Theme.animFast
                                easing.type: Easing.OutCubic
                            }
                        }
                    }

                    Text {
                        text: "\u25B4"
                        color: Theme.textMuted
                        font.pixelSize: 9
                        rotation: modelPopup.opened ? 180 : 0
                        anchors.verticalCenter: parent.verticalCenter

                        Behavior on rotation {
                            NumberAnimation {
                                duration: Theme.animFast
                                easing.type: Easing.OutCubic
                            }
                        }
                    }
                }

                Popup {
                    id: modelPopup
                    x: 0
                    y: -height - 8
                    width: 292
                    height: modelMenu.implicitHeight + 8
                    padding: 4
                    modal: false
                    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                    transformOrigin: Item.BottomLeft

                    enter: Transition {
                        ParallelAnimation {
                            NumberAnimation {
                                property: "opacity"
                                from: 0
                                to: 1
                                duration: Theme.animFast
                                easing.type: Easing.OutCubic
                            }
                            NumberAnimation {
                                property: "scale"
                                from: 0.975
                                to: 1
                                duration: Theme.animBase
                                easing.type: Easing.OutCubic
                            }
                        }
                    }
                    exit: Transition {
                        ParallelAnimation {
                            NumberAnimation {
                                property: "opacity"
                                to: 0
                                duration: Theme.animFast
                            }
                            NumberAnimation {
                                property: "scale"
                                to: 0.985
                                duration: Theme.animFast
                                easing.type: Easing.InCubic
                            }
                        }
                    }

                    background: Rectangle {
                        radius: 12
                        color: Theme.panelRaised
                        border.color: Theme.borderStrong
                    }

                    contentItem: Column {
                        id: modelMenu
                        width: modelPopup.availableWidth

                        Repeater {
                            model: root.modelOptions

                            ItemDelegate {
                                id: modelItem
                                required property int index
                                required property var modelData
                                width: modelMenu.width
                                height: 46
                                hoverEnabled: true
                                readonly property bool selected: modelPill.selectedIndex === modelItem.index

                                background: Rectangle {
                                    radius: 8
                                    color: modelItem.down ? Theme.selection
                                                          : (modelItem.hovered ? Theme.panelHover
                                                                               : "transparent")
                                    Behavior on color {
                                        ColorAnimation { duration: Theme.animFast }
                                    }
                                }

                                contentItem: Item {
                                    scale: modelItem.down ? 0.985 : 1
                                    Behavior on scale {
                                        NumberAnimation {
                                            duration: Theme.animFast
                                            easing.type: Easing.OutCubic
                                        }
                                    }

                                    Rectangle {
                                        x: 3
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 2
                                        height: modelItem.selected ? 18 : 5
                                        radius: 1
                                        color: "#55adff"
                                        opacity: modelItem.selected ? 1 : 0
                                        Behavior on height {
                                            NumberAnimation {
                                                duration: Theme.animBase
                                                easing.type: Easing.OutCubic
                                            }
                                        }
                                        Behavior on opacity {
                                            NumberAnimation { duration: Theme.animFast }
                                        }
                                    }

                                    SvgIcon {
                                        id: optionIcon
                                        x: 12
                                        anchors.verticalCenter: parent.verticalCenter
                                        source: Theme.icon("sparkle")
                                        iconSize: 12
                                        color: modelItem.selected ? "#79c4ff" : Theme.textMuted
                                        Behavior on color {
                                            ColorAnimation { duration: Theme.animFast }
                                        }
                                    }

                                    Column {
                                        x: 32
                                        width: parent.width - 78
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: 2

                                        Text {
                                            text: String(modelItem.modelData.name)
                                            color: Theme.text
                                            font.family: Theme.uiFont
                                            font.pixelSize: 11
                                            font.weight: Font.DemiBold
                                        }
                                        Text {
                                            width: parent.width
                                            text: String(modelItem.modelData.description)
                                            color: Theme.textMuted
                                            font.family: Theme.uiFont
                                            font.pixelSize: 9
                                            elide: Text.ElideRight
                                        }
                                    }

                                    Rectangle {
                                        visible: Boolean(modelItem.modelData.delayed)
                                        anchors.right: parent.right
                                        anchors.rightMargin: modelItem.selected ? 28 : 8
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 27
                                        height: 16
                                        radius: 8
                                        color: modelItem.selected ? "#233f58" : Theme.field
                                        border.width: modelItem.selected ? 1 : 0
                                        border.color: "#4da8f5"

                                        Behavior on color {
                                            ColorAnimation { duration: Theme.animFast }
                                        }
                                        Behavior on anchors.rightMargin {
                                            NumberAnimation {
                                                duration: Theme.animBase
                                                easing.type: Easing.OutCubic
                                            }
                                        }

                                        Text {
                                            anchors.centerIn: parent
                                            text: "24H"
                                            color: modelItem.selected ? "#9bd5ff" : Theme.textSecondary
                                            font.family: Theme.monoFont
                                            font.pixelSize: 8
                                            font.weight: Font.DemiBold
                                        }
                                    }

                                    SvgIcon {
                                        visible: modelItem.selected
                                        anchors.right: parent.right
                                        anchors.rightMargin: 9
                                        anchors.verticalCenter: parent.verticalCenter
                                        source: Theme.icon("check")
                                        iconSize: 11
                                        color: "#79c4ff"

                                        NumberAnimation on scale {
                                            from: 0.65
                                            to: 1
                                            duration: Theme.animBase
                                            easing.type: Easing.OutBack
                                            running: modelItem.selected && modelPopup.opened
                                        }
                                    }
                                }

                                onClicked: root.selectModel(index)
                            }
                        }
                    }
                }
            }

            Rectangle {
                id: effortCycler
                property int index: root.availableEfforts.length > 1 ? 1 : 0
                Layout.preferredWidth: effortRow.implicitWidth + 18
                Layout.preferredHeight: 30
                radius: 15
                color: effortClick.containsMouse ? Theme.selection : "transparent"
                enabled: !root.busy && root.availableEfforts.length > 0 && !root.fixedHighThinking

                ToolTip.visible: effortHover.containsMouse
                ToolTip.delay: 500
                ToolTip.text: root.fixedHighThinking
                              ? "Gemini 3.6 always uses High thinking"
                              : "Click to change thinking level"

                MouseArea {
                    id: effortHover
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.NoButton
                }

                MouseArea {
                    id: effortClick
                    anchors.fill: parent
                    cursorShape: root.fixedHighThinking ? Qt.ArrowCursor : Qt.PointingHandCursor
                    hoverEnabled: true
                    enabled: !root.fixedHighThinking
                    onClicked: root.cycleEffort()
                }

                Row {
                    id: effortRow
                    anchors.centerIn: parent
                    spacing: 6

                    Item {
                        width: 22
                        height: 14
                        anchors.verticalCenter: parent.verticalCenter

                        Repeater {
                            model: 5

                            Rectangle {
                                required property int index
                                x: index * 4.25
                                y: 11.5 - index * 2
                                width: 2.5
                                height: 3 + index * 2
                                radius: 1
                                color: root.highChargeActive ? "#69b9ff" : Theme.textSecondary
                                opacity: index < root.effortIntensity(root.selectedEffort) ? 1 : 0.2
                                Behavior on opacity { NumberAnimation { duration: Theme.animFast } }
                                Behavior on color { ColorAnimation { duration: Theme.animFast } }
                            }
                        }
                    }

                    Text {
                        id: effortLabel
                        text: root.selectedEffort
                        color: root.highChargeActive ? "#8acbff"
                                                     : (effortClick.containsMouse ? Theme.text
                                                                                  : Theme.textSecondary)
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                        Behavior on color { ColorAnimation { duration: Theme.animFast } }
                    }
                }
            }

            Item { Layout.fillWidth: true }

            Text {
                visible: !root.backendConfigured
                text: "API key required"
                color: Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 9
            }

            IconButton {
                iconSource: Theme.icon("plus")
                toolTip: "Attach images"
                buttonSize: 28
                enabled: !root.busy && root.attachments.length < root.maxAttachments
                onClicked: root.attachRequested()
            }

            LoadingState {
                visible: root.busy
                running: root.busy
                variant: root.busyVariant
                label: root.busyLabel
            }

            AbstractButton {
                id: actionButton
                Accessible.role: Accessible.Button
                Accessible.name: root.busy ? "Stop response" : "Send message"
                Layout.preferredWidth: 32
                Layout.preferredHeight: 32
                enabled: root.busy
                         || (root.backendConfigured && promptArea.text.trim().length > 0)

                background: Rectangle {
                    radius: width / 2
                    color: actionButton.enabled
                           ? (actionButton.pressed ? Theme.selectionBorder : Theme.accent)
                           : Theme.field
                    Behavior on color { ColorAnimation { duration: Theme.animFast } }
                }

                contentItem: Item {
                    SvgIcon {
                        anchors.centerIn: parent
                        source: Theme.icon("arrow-up")
                        iconSize: 16
                        color: actionButton.enabled ? Theme.accentText : Theme.textMuted
                        opacity: root.busy ? 0 : 1
                        scale: !root.busy && actionButton.enabled ? 1 : 0.9
                        Behavior on opacity { NumberAnimation { duration: Theme.animFast } }
                        Behavior on color { ColorAnimation { duration: Theme.animFast } }
                        Behavior on scale {
                            NumberAnimation {
                                duration: Theme.animFast
                                easing.type: Easing.OutCubic
                            }
                        }
                    }

                    Rectangle {
                        anchors.centerIn: parent
                        width: 10
                        height: 10
                        radius: 2
                        color: Theme.accentText
                        opacity: root.busy ? 1 : 0
                        scale: root.busy ? 1 : 0.5
                        Behavior on opacity { NumberAnimation { duration: Theme.animFast } }
                        Behavior on scale {
                            NumberAnimation {
                                duration: Theme.animFast
                                easing.type: Easing.OutBack
                            }
                        }
                    }
                }

                onClicked: root.trySubmit()
            }
        }
    }

    Shape {
        id: highChargeGlow
        anchors.fill: parent
        visible: root.highChargeActive
        opacity: root.highChargeOpacity * 0.52
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            fillColor: "transparent"
            strokeColor: "#1ea0ff"
            strokeWidth: 5.0
            cosmeticStroke: true
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            trim.start: Math.max(0, root.highChargeProgress - 0.27)
            trim.end: Math.max(0, root.highChargeProgress - 0.012)
            startX: highChargeGlow.width / 2
            startY: highChargeGlow.height - 2
            PathLine { x: 18; y: highChargeGlow.height - 2 }
            PathArc { x: 2; y: highChargeGlow.height - 18; radiusX: 16; radiusY: 16; direction: PathArc.Clockwise }
            PathLine { x: 2; y: 18 }
            PathArc { x: 18; y: 2; radiusX: 16; radiusY: 16; direction: PathArc.Clockwise }
            PathLine { x: highChargeGlow.width / 2; y: 2 }
        }

        ShapePath {
            fillColor: "transparent"
            strokeColor: "#1ea0ff"
            strokeWidth: 5.0
            cosmeticStroke: true
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            trim.start: Math.max(0, root.highChargeProgress - 0.27)
            trim.end: Math.max(0, root.highChargeProgress - 0.012)
            startX: highChargeGlow.width / 2
            startY: highChargeGlow.height - 2
            PathLine { x: highChargeGlow.width - 18; y: highChargeGlow.height - 2 }
            PathArc { x: highChargeGlow.width - 2; y: highChargeGlow.height - 18; radiusX: 16; radiusY: 16; direction: PathArc.Counterclockwise }
            PathLine { x: highChargeGlow.width - 2; y: 18 }
            PathArc { x: highChargeGlow.width - 18; y: 2; radiusX: 16; radiusY: 16; direction: PathArc.Counterclockwise }
            PathLine { x: highChargeGlow.width / 2; y: 2 }
        }
    }

    Shape {
        id: highChargeCore
        anchors.fill: parent
        visible: root.highChargeActive
        opacity: root.highChargeOpacity
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            fillColor: "transparent"
            strokeColor: "#9ad8ff"
            strokeWidth: 2.0
            cosmeticStroke: true
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            trim.start: Math.max(0, root.highChargeProgress - 0.105)
            trim.end: root.highChargeProgress
            startX: highChargeCore.width / 2
            startY: highChargeCore.height - 2
            PathLine { x: 18; y: highChargeCore.height - 2 }
            PathArc { x: 2; y: highChargeCore.height - 18; radiusX: 16; radiusY: 16; direction: PathArc.Clockwise }
            PathLine { x: 2; y: 18 }
            PathArc { x: 18; y: 2; radiusX: 16; radiusY: 16; direction: PathArc.Clockwise }
            PathLine { x: highChargeCore.width / 2; y: 2 }
        }

        ShapePath {
            fillColor: "transparent"
            strokeColor: "#9ad8ff"
            strokeWidth: 2.0
            cosmeticStroke: true
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            trim.start: Math.max(0, root.highChargeProgress - 0.105)
            trim.end: root.highChargeProgress
            startX: highChargeCore.width / 2
            startY: highChargeCore.height - 2
            PathLine { x: highChargeCore.width - 18; y: highChargeCore.height - 2 }
            PathArc { x: highChargeCore.width - 2; y: highChargeCore.height - 18; radiusX: 16; radiusY: 16; direction: PathArc.Counterclockwise }
            PathLine { x: highChargeCore.width - 2; y: 18 }
            PathArc { x: highChargeCore.width - 18; y: 2; radiusX: 16; radiusY: 16; direction: PathArc.Counterclockwise }
            PathLine { x: highChargeCore.width / 2; y: 2 }
        }
    }

    Rectangle {
        id: highChargeImpactGlow
        z: 2
        anchors.horizontalCenter: parent.horizontalCenter
        y: 0.5
        width: 12 + 44 * root.highChargeImpact
        height: 5
        radius: 2.5
        color: "#1ea0ff"
        opacity: root.highChargeImpact * 0.45
        visible: opacity > 0.01
    }

    Rectangle {
        id: highChargeImpactCore
        z: 3
        anchors.horizontalCenter: parent.horizontalCenter
        y: 1.5
        width: 6 + 28 * root.highChargeImpact
        height: 2
        radius: 1
        color: "#9ad8ff"
        opacity: root.highChargeImpact
        visible: opacity > 0.01
    }

    SequentialAnimation {
        id: highCharge

        ScriptAction {
            script: {
                root.highChargeProgress = 0;
                root.highChargeOpacity = 0;
                root.highChargeImpact = 0;
            }
        }
        ParallelAnimation {
            NumberAnimation {
                target: root
                property: "highChargeProgress"
                from: 0
                to: 1
                duration: 720
                easing.type: Easing.InQuad
            }
            NumberAnimation {
                target: root
                property: "highChargeOpacity"
                from: 0
                to: 1
                duration: 90
                easing.type: Easing.OutCubic
            }
        }
        ParallelAnimation {
            NumberAnimation {
                target: root
                property: "highChargeOpacity"
                to: 0
                duration: 175
                easing.type: Easing.OutQuad
            }
            SequentialAnimation {
                NumberAnimation {
                    target: root
                    property: "highChargeImpact"
                    from: 0
                    to: 1
                    duration: 65
                    easing.type: Easing.OutCubic
                }
                NumberAnimation {
                    target: root
                    property: "highChargeImpact"
                    to: 0
                    duration: 140
                    easing.type: Easing.OutQuad
                }
            }
        }
        ScriptAction {
            script: {
                root.highChargeProgress = 0;
                root.highChargeImpact = 0;
            }
        }
    }
}
