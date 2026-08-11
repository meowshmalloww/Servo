pragma ComponentBehavior: Bound

import QtCore
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../components"

Item {
    id: root

    readonly property var selectedWorld: WorldLibraryModel.selectedWorld
    readonly property bool hasSelection: WorldLibraryModel.hasSelection
    readonly property url selectedPreviewUrl: {
        const value = root.selectedWorld
                      ? root.selectedWorld.previewUrl : undefined;
        return value === undefined || value === null ? "" : value;
    }
    readonly property string selectedPlyPath: root.selectedWorld
                                                ? String(root.selectedWorld.plyPath || "")
                                                : ""
    property string noticeText: ""
    property bool exploreMode: false
    property bool moveForward: false
    property bool moveBackward: false
    property bool moveLeft: false
    property bool moveRight: false
    property bool moveUp: false
    property bool moveDown: false
    property int visualizationMode: 0

    onSelectedPlyPathChanged: {
        if (root.selectedPlyPath.length === 0)
            root.exploreMode = false;
    }
    onExploreModeChanged: {
        if (!root.exploreMode)
            root.stopMovement();
    }

    function resetLayout() {
        Session.viewportFocusMode = false;
        worldLibrary.SplitView.preferredWidth = 330;
        worldInspector.SplitView.preferredWidth = 320;
    }

    function stopMovement() {
        root.moveForward = false;
        root.moveBackward = false;
        root.moveLeft = false;
        root.moveRight = false;
        root.moveUp = false;
        root.moveDown = false;
    }

    function toggleExplore() {
        if (!root.hasSelection || root.selectedPlyPath.length === 0)
            return;
        root.exploreMode = !root.exploreMode;
        if (root.exploreMode)
            gaussianView.forceActiveFocus();
        else
            root.stopMovement();
    }

    function sortIndex(mode) {
        if (mode === "name")
            return 1;
        if (mode === "size")
            return 2;
        return 0;
    }

    function metricText(value, digits) {
        const number = Number(value);
        return Number.isFinite(number) && number >= 0 ? number.toFixed(digits) : "—";
    }

    function visualizationDescription(mode) {
        if (mode === 1)
            return "False-color relative camera depth inferred from the Gaussian field; this is not LiDAR or metres without a scale anchor.";
        if (mode === 2)
            return "Shortest-axis splat orientation exposes structural inconsistency; it is a diagnostic cue, not a collision surface normal.";
        if (mode === 3)
            return "Accumulated opacity support: dark areas are gaps, weak evidence, or unseen space and must not be treated as drivable.";
        return "Photometric Gaussian appearance for visual review; good RGB alone does not prove road geometry or autonomy safety.";
    }

    function openRenameDialog() {
        if (!root.hasSelection)
            return;
        renameDialog.worldId = String(root.selectedWorld.worldId);
        renameField.text = String(root.selectedWorld.displayName);
        renameDialog.open();
        renameField.forceActiveFocus();
        renameField.selectAll();
    }

    function openDeleteDialog() {
        if (!root.hasSelection)
            return;
        deleteDialog.worldId = String(root.selectedWorld.worldId);
        deleteDialog.worldName = String(root.selectedWorld.displayName);
        deleteDialog.storageText = String(root.selectedWorld.sizeText);
        deleteDialog.open();
    }

    Settings {
        id: layoutSettings
        category: "WorldEditorLayout"
        property var horizontalSplitState
        property int layoutSchema: 0
    }

    Timer {
        id: noticeTimer
        interval: 5000
        onTriggered: root.noticeText = ""
    }

    FrameAnimation {
        running: root.exploreMode && gaussianView.ready
                 && (root.moveForward || root.moveBackward
                     || root.moveLeft || root.moveRight
                     || root.moveUp || root.moveDown)
        onTriggered: gaussianView.moveCamera(
                         (root.moveForward ? 1 : 0) - (root.moveBackward ? 1 : 0),
                         (root.moveRight ? 1 : 0) - (root.moveLeft ? 1 : 0),
                         (root.moveUp ? 1 : 0) - (root.moveDown ? 1 : 0),
                         Math.min(frameTime, 0.05))
    }

    Shortcut {
        sequence: "Ctrl+E"
        enabled: root.hasSelection && root.selectedPlyPath.length > 0
        onActivated: root.toggleExplore()
    }

    onVisibleChanged: {
        if (!visible)
            root.stopMovement();
    }

    Component.onCompleted: {
        if (layoutSettings.layoutSchema === 1
                && layoutSettings.horizontalSplitState !== undefined) {
            worldSplit.restoreState(layoutSettings.horizontalSplitState);
        } else {
            root.resetLayout();
            layoutSettings.layoutSchema = 1;
        }
        WorldLibraryModel.refresh();
    }

    Component.onDestruction: {
        if (!Session.viewportFocusMode)
            layoutSettings.horizontalSplitState = worldSplit.saveState();
    }

    Connections {
        target: Session

        function onResetWorkspaceLayoutRequested() {
            root.resetLayout();
        }
    }

    Connections {
        target: WorldLibraryModel

        function onWorldDeleted(worldId, displayName, recoveredBytes) {
            root.noticeText = displayName + " was deleted. "
                              + root.metricStorage(recoveredBytes) + " recovered.";
            noticeTimer.restart();
        }
    }

    function metricStorage(bytes) {
        const value = Number(bytes);
        if (!Number.isFinite(value) || value < 0)
            return "Storage";
        const units = ["B", "KiB", "MiB", "GiB", "TiB"];
        let scaled = value;
        let unit = 0;
        while (scaled >= 1024 && unit < units.length - 1) {
            scaled /= 1024;
            ++unit;
        }
        return (unit === 0 ? Math.round(scaled).toString()
                           : scaled.toFixed(scaled < 10 ? 2 : 1)) + " " + units[unit];
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "Worlds"
            subtitle: WorldLibraryModel.busy
                      ? WorldLibraryModel.busyText
                      : (WorldLibraryModel.totalCount + " created · "
                         + WorldLibraryModel.totalBytesText + " local")
            iconSource: Theme.icon("world")
            Layout.fillWidth: true

            TextButton {
                text: "Create world"
                iconSource: Theme.icon("plus")
                onClicked: Session.workspaceIndex = 0
            }

            TextButton {
                text: "Refresh"
                iconSource: Theme.icon("refresh")
                enabled: !WorldLibraryModel.busy
                onClicked: WorldLibraryModel.refresh()
            }
        }

        Rectangle {
            visible: WorldLibraryModel.lastError.length > 0 || root.noticeText.length > 0
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 38 : 0
            color: WorldLibraryModel.lastError.length > 0 ? "#332123" : "#213024"
            border.width: 1
            border.color: WorldLibraryModel.lastError.length > 0
                          ? Theme.error : Theme.success

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 11
                anchors.rightMargin: 5
                spacing: 8

                SvgIcon {
                    source: Theme.icon(WorldLibraryModel.lastError.length > 0
                                       ? "error" : "check")
                    iconSize: 14
                }
                Text {
                    Layout.fillWidth: true
                    text: WorldLibraryModel.lastError.length > 0
                          ? WorldLibraryModel.lastError : root.noticeText
                    color: WorldLibraryModel.lastError.length > 0
                           ? Theme.error : Theme.success
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }
                IconButton {
                    iconSource: Theme.icon("close")
                    buttonSize: 26
                    toolTip: "Dismiss"
                    onClicked: {
                        WorldLibraryModel.clearLastError();
                        root.noticeText = "";
                    }
                }
            }
        }

        SplitView {
            id: worldSplit
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: SplitHandle {}

            Panel {
                id: worldLibrary
                visible: !Session.viewportFocusMode
                SplitView.preferredWidth: 330
                SplitView.minimumWidth: 270
                SplitView.maximumWidth: 520

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Created worlds"
                        subtitle: WorldLibraryModel.filterText.length > 0
                                  ? (WorldLibraryModel.count + " / "
                                     + WorldLibraryModel.totalCount)
                                  : WorldLibraryModel.totalCount.toString()
                        iconSource: Theme.icon("folder")
                        actionIcon: Theme.icon("refresh")
                        actionToolTip: "Rescan local worlds"
                        onActionTriggered: WorldLibraryModel.refresh()
                        Layout.fillWidth: true
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 42
                        Layout.minimumHeight: 42
                        Layout.maximumHeight: 42
                        Layout.leftMargin: 7
                        Layout.rightMargin: 7
                        spacing: 6

                        SearchField {
                            Layout.fillWidth: true
                            hint: "Search worlds"
                            text: WorldLibraryModel.filterText
                            onTextChanged: WorldLibraryModel.filterText = text
                        }

                        SelectField {
                            Layout.preferredWidth: 92
                            Layout.preferredHeight: Theme.controlHeight
                            Layout.fillHeight: false
                            model: ["Newest", "Name", "Largest"]
                            currentIndex: root.sortIndex(WorldLibraryModel.sortMode)
                            onActivated: {
                                WorldLibraryModel.sortMode = currentIndex === 1
                                                             ? "name"
                                                             : (currentIndex === 2
                                                                ? "size" : "newest");
                            }
                        }
                    }

                    ListView {
                        id: worldList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: WorldLibraryModel
                        visible: count > 0 || WorldLibraryModel.busy
                        currentIndex: WorldLibraryModel.selectedIndex
                        boundsBehavior: Flickable.StopAtBounds
                        spacing: 1
                        reuseItems: true
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        delegate: Rectangle {
                            id: worldDelegate

                            required property int index
                            required property string worldId
                            required property string displayName
                            required property string sourceSummary
                            required property string createdText
                            required property string sizeText
                            required property string gaussianText
                            required property string qualityLabel
                            required property string qualityTone
                            required property url previewUrl

                            width: worldList.width
                            height: 98
                            color: worldDelegate.worldId === WorldLibraryModel.selectedWorldId
                                   ? Theme.selection
                                   : (worldArea.containsMouse ? Theme.panelHover
                                                              : Theme.panel)
                            border.width: 1
                            border.color: worldDelegate.worldId
                                          === WorldLibraryModel.selectedWorldId
                                          ? Theme.selectionBorder : Theme.borderSoft

                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 8
                                spacing: 9

                                Rectangle {
                                    Layout.preferredWidth: 84
                                    Layout.fillHeight: true
                                    color: Theme.viewport
                                    border.width: 1
                                    border.color: Theme.border
                                    clip: true

                                    Image {
                                        anchors.fill: parent
                                        source: worldDelegate.previewUrl
                                        visible: source.toString().length > 0
                                        asynchronous: true
                                        cache: true
                                        fillMode: Image.PreserveAspectCrop
                                        sourceSize.width: 240
                                    }

                                    SvgIcon {
                                        anchors.centerIn: parent
                                        visible: worldDelegate.previewUrl.toString().length === 0
                                        source: Theme.icon("world")
                                        iconSize: 24
                                        opacity: 0.55
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    spacing: 3

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 5
                                        Text {
                                            Layout.fillWidth: true
                                            text: worldDelegate.displayName
                                            color: Theme.text
                                            font.family: Theme.uiFont
                                            font.pixelSize: 11
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideRight
                                        }
                                        StatusBadge {
                                            text: worldDelegate.qualityLabel
                                            tone: worldDelegate.qualityTone
                                        }
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: worldDelegate.sourceSummary
                                        color: Theme.textMuted
                                        font.family: Theme.uiFont
                                        font.pixelSize: 9
                                        elide: Text.ElideMiddle
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: worldDelegate.gaussianText + " splats · "
                                              + worldDelegate.sizeText
                                        color: Theme.textSecondary
                                        font.family: Theme.monoFont
                                        font.pixelSize: 8
                                        elide: Text.ElideRight
                                    }

                                    Item { Layout.fillHeight: true }

                                    Text {
                                        Layout.fillWidth: true
                                        text: worldDelegate.createdText
                                        color: Theme.textDisabled
                                        font.family: Theme.uiFont
                                        font.pixelSize: 8
                                        elide: Text.ElideRight
                                    }
                                }
                            }

                            MouseArea {
                                id: worldArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: WorldLibraryModel.selectWorld(worldDelegate.worldId)
                            }
                        }
                    }

                    EmptyState {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: worldList.count === 0 && !WorldLibraryModel.busy
                        iconSource: Theme.icon("world")
                        title: WorldLibraryModel.filterText.length > 0
                               ? "No matching worlds" : "No created worlds"
                        description: WorldLibraryModel.filterText.length > 0
                                     ? "Change the search text to show more worlds."
                                     : "A verified reconstruction appears here automatically after publishing."
                        actionText: WorldLibraryModel.filterText.length > 0
                                    ? "Clear search" : "Create world"
                        actionIcon: WorldLibraryModel.filterText.length > 0
                                    ? Theme.icon("close") : Theme.icon("plus")
                        onActionRequested: {
                            if (WorldLibraryModel.filterText.length > 0)
                                WorldLibraryModel.filterText = "";
                            else
                                Session.workspaceIndex = 0;
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        color: Theme.chrome
                        border.width: 1
                        border.color: Theme.borderSoft

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 9
                            anchors.rightMargin: 9
                            spacing: 7
                            SvgIcon {
                                source: Theme.icon("storage")
                                iconSize: 13
                            }
                            Text {
                                text: WorldLibraryModel.totalBytesText + " used by completed jobs"
                                color: Theme.textMuted
                                font.family: Theme.uiFont
                                font.pixelSize: 9
                            }
                            Item { Layout.fillWidth: true }
                            BusyIndicator {
                                visible: WorldLibraryModel.busy
                                running: visible
                                implicitWidth: 15
                                implicitHeight: 15
                            }
                        }
                    }
                }
            }

            Panel {
                id: previewPanel
                SplitView.fillWidth: true
                SplitView.minimumWidth: 440
                color: Theme.viewport

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        color: Theme.chrome
                        border.width: 1
                        border.color: Theme.borderSoft

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 6
                            spacing: 8

                            StatusBadge {
                                visible: root.hasSelection
                                text: "Selected"
                                tone: "info"
                            }
                            Text {
                                Layout.fillWidth: true
                                text: root.hasSelection
                                      ? String(root.selectedWorld.displayName)
                                      : "No world selected"
                                color: Theme.textSecondary
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                                elide: Text.ElideRight
                            }
                            TextButton {
                                visible: root.hasSelection
                                compact: true
                                text: root.exploreMode ? "Validation" : "Explore"
                                iconSource: Theme.icon(root.exploreMode ? "image" : "play")
                                enabled: root.selectedPlyPath.length > 0
                                onClicked: root.toggleExplore()
                            }
                            TextButton {
                                visible: root.hasSelection
                                compact: true
                                text: "Open bundle"
                                iconSource: Theme.icon("folder")
                                onClicked: WorldLibraryModel.openWorldFolder(
                                               String(root.selectedWorld.worldId))
                            }
                            IconButton {
                                iconSource: Theme.icon(Session.viewportFocusMode
                                                      ? "minimize" : "maximize")
                                toolTip: Session.viewportFocusMode
                                         ? "Restore library and inspector"
                                         : "Focus preview"
                                selected: Session.viewportFocusMode
                                buttonSize: 25
                                onClicked: Session.viewportFocusMode = !Session.viewportFocusMode
                            }
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        Rectangle {
                            anchors.fill: parent
                            color: Theme.viewport

                            Image {
                                id: validationPreview
                                anchors.fill: parent
                                anchors.margins: 18
                                source: root.hasSelection
                                        ? root.selectedPreviewUrl : ""
                                visible: root.hasSelection && !root.exploreMode
                                         && source.toString().length > 0
                                asynchronous: true
                                cache: true
                                fillMode: Image.PreserveAspectFit
                                sourceSize.width: 2048
                                sourceSize.height: 1200
                            }

                            EmptyState {
                                anchors.fill: parent
                                visible: !root.hasSelection
                                iconSource: Theme.icon("world")
                                title: "Select a created world"
                                description: "Completed reconstructions load here automatically; no folder drag or manual import is required."
                                actionText: "Create world"
                                actionIcon: Theme.icon("plus")
                                onActionRequested: Session.workspaceIndex = 0
                            }

                            EmptyState {
                                anchors.fill: parent
                                visible: root.hasSelection && !root.exploreMode
                                         && root.selectedPreviewUrl.toString().length === 0
                                iconSource: Theme.icon("image")
                                title: "World bundle loaded"
                                description: "This build has no validation preview image. Its verified Gaussian PLY remains available in the bundle."
                            }

                            GaussianSplatView {
                                id: gaussianView
                                z: 0
                                anchors.fill: parent
                                visible: root.hasSelection && root.exploreMode
                                source: visible ? root.selectedPlyPath : ""
                                visualizationMode: root.visualizationMode
                                focus: visible
                                onActiveFocusChanged: {
                                    if (!activeFocus)
                                        root.stopMovement();
                                }

                                Keys.onPressed: event => {
                                    if (event.key === Qt.Key_W || event.key === Qt.Key_Up)
                                        root.moveForward = true;
                                    else if (event.key === Qt.Key_S || event.key === Qt.Key_Down)
                                        root.moveBackward = true;
                                    else if (event.key === Qt.Key_A || event.key === Qt.Key_Left)
                                        root.moveLeft = true;
                                    else if (event.key === Qt.Key_D || event.key === Qt.Key_Right)
                                        root.moveRight = true;
                                    else if (event.key === Qt.Key_E || event.key === Qt.Key_Space)
                                        root.moveUp = true;
                                    else if (event.key === Qt.Key_Q || event.key === Qt.Key_Control)
                                        root.moveDown = true;
                                    else if (event.key === Qt.Key_R)
                                        gaussianView.resetCamera();
                                    else if (event.key === Qt.Key_1)
                                        root.visualizationMode = 0;
                                    else if (event.key === Qt.Key_2)
                                        root.visualizationMode = 1;
                                    else if (event.key === Qt.Key_3)
                                        root.visualizationMode = 2;
                                    else if (event.key === Qt.Key_4)
                                        root.visualizationMode = 3;
                                    else if (event.key === Qt.Key_Escape)
                                        root.exploreMode = false;
                                    else
                                        return;
                                    event.accepted = true;
                                }

                                Keys.onReleased: event => {
                                    if (event.isAutoRepeat)
                                        return;
                                    if (event.key === Qt.Key_W || event.key === Qt.Key_Up)
                                        root.moveForward = false;
                                    else if (event.key === Qt.Key_S || event.key === Qt.Key_Down)
                                        root.moveBackward = false;
                                    else if (event.key === Qt.Key_A || event.key === Qt.Key_Left)
                                        root.moveLeft = false;
                                    else if (event.key === Qt.Key_D || event.key === Qt.Key_Right)
                                        root.moveRight = false;
                                    else if (event.key === Qt.Key_E || event.key === Qt.Key_Space)
                                        root.moveUp = false;
                                    else if (event.key === Qt.Key_Q || event.key === Qt.Key_Control)
                                        root.moveDown = false;
                                    else
                                        return;
                                    event.accepted = true;
                                }

                                MouseArea {
                                    property real previousX: 0
                                    property real previousY: 0
                                    anchors.fill: parent
                                    acceptedButtons: Qt.LeftButton
                                    hoverEnabled: true
                                    cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                                    onPressed: mouse => {
                                        previousX = mouse.x;
                                        previousY = mouse.y;
                                        gaussianView.forceActiveFocus();
                                    }
                                    onPositionChanged: mouse => {
                                        if (!pressed)
                                            return;
                                        gaussianView.look(mouse.x - previousX,
                                                          mouse.y - previousY);
                                        previousX = mouse.x;
                                        previousY = mouse.y;
                                    }
                                    onWheel: wheel => {
                                        gaussianView.changeMovementSpeed(wheel.angleDelta.y / 120.0);
                                        wheel.accepted = true;
                                    }
                                }
                            }

                            Rectangle {
                                z: 2
                                anchors.centerIn: parent
                                width: Math.min(440, parent.width - 48)
                                height: gaussianView.errorString.length > 0 ? 142 : 112
                                visible: root.exploreMode
                                         && (gaussianView.loading
                                             || gaussianView.errorString.length > 0)
                                color: "#e5191c1e"
                                border.width: 1
                                border.color: gaussianView.errorString.length > 0
                                              ? Theme.error : Theme.borderStrong
                                radius: Theme.cornerPopup

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 14
                                    spacing: 8
                                    BusyIndicator {
                                        Layout.alignment: Qt.AlignHCenter
                                        visible: gaussianView.loading
                                        running: visible
                                        implicitWidth: 24
                                        implicitHeight: 24
                                    }
                                    SvgIcon {
                                        Layout.alignment: Qt.AlignHCenter
                                        visible: gaussianView.errorString.length > 0
                                        source: Theme.icon("error")
                                        iconSize: 20
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: gaussianView.errorString.length > 0
                                              ? gaussianView.errorString
                                              : gaussianView.statusText
                                        color: gaussianView.errorString.length > 0
                                               ? Theme.error : Theme.text
                                        font.family: Theme.uiFont
                                        font.pixelSize: 10
                                        horizontalAlignment: Text.AlignHCenter
                                        wrapMode: Text.WordWrap
                                    }
                                    ProgressBar {
                                        Layout.fillWidth: true
                                        visible: gaussianView.loading
                                        indeterminate: true
                                        from: 0
                                        to: 1
                                        value: gaussianView.loadProgress
                                    }
                                }
                            }

                            Rectangle {
                                z: 2
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.margins: 12
                                height: 72
                                visible: root.exploreMode && gaussianView.ready
                                color: "#e5191c1e"
                                border.width: 1
                                border.color: Theme.borderStrong
                                radius: Theme.cornerPopup

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 11
                                    anchors.rightMargin: 8
                                    spacing: 12
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        Text {
                                            text: gaussianView.followPath
                                                  ? "EXPLORE / SMOOTHED OBSERVED CAMERA CORRIDOR"
                                                  : "EXPLORE / FREE FLY (OUTSIDE COVERAGE MAY FAIL)"
                                            color: Theme.textSecondary
                                            font.family: Theme.uiFont
                                            font.pixelSize: 8
                                            font.weight: Font.DemiBold
                                        }
                                        Text {
                                            text: gaussianView.followPath
                                                  ? "W/S follow capture | A/D and E/Q bounded offsets | drag to look | R resets"
                                                  : "WASD free fly | E/Q vertical | drag to look | R resets"
                                            color: Theme.textMuted
                                            font.family: Theme.uiFont
                                            font.pixelSize: 9
                                        }
                                    }
                                    TextButton {
                                        compact: true
                                        enabled: gaussianView.pathAvailable
                                        text: gaussianView.followPath ? "Smoothed path" : "Free fly"
                                        toolTip: gaussianView.followPath
                                                 ? "W/S follows a height-smoothed source-camera path that preserves sustained grades while removing pose bounce."
                                                 : "Free fly can expose unobserved surfaces and is not verified geometry."
                                        onClicked: {
                                            gaussianView.followPath = !gaussianView.followPath;
                                            gaussianView.forceActiveFocus();
                                        }
                                    }
                                    Text {
                                        text: gaussianView.visibleGaussianCount.toLocaleString()
                                              + " submitted\n"
                                              + (gaussianView.followPath
                                                 ? (gaussianView.pathProgress * 100).toFixed(0) + "% path"
                                                 : gaussianView.movementSpeed.toFixed(2) + " u/s")
                                        color: Theme.textSecondary
                                        font.family: Theme.monoFont
                                        font.pixelSize: 8
                                        horizontalAlignment: Text.AlignRight
                                    }
                                    Text {
                                        text: gaussianView.renderFps > 0
                                              ? gaussianView.renderFps.toFixed(0) + " submit Hz / "
                                                + gaussianView.geometryUpdateFps.toFixed(1) + " geometry Hz\n"
                                                + gaussianView.frameTimeMs.toFixed(1) + " ms CPU / "
                                                + (gaussianView.gpuTimeMs > 0
                                                   ? gaussianView.gpuTimeMs.toFixed(1) + " ms GPU / "
                                                   : "GPU n/a / ")
                                                + "same-frame geometry / lag "
                                                + gaussianView.cameraRevisionLag
                                              : "Ready\nVulkan"
                                        color: Theme.text
                                        font.family: Theme.monoFont
                                        font.pixelSize: 9
                                        horizontalAlignment: Text.AlignRight
                                    }
                                    IconButton {
                                        iconSource: Theme.icon("focus")
                                        toolTip: "Return to the first registered camera"
                                        buttonSize: 28
                                        onClicked: {
                                            gaussianView.resetCamera();
                                            gaussianView.forceActiveFocus();
                                        }
                                    }
                                }
                            }

                            Rectangle {
                                id: diagnosticPalette
                                z: 3
                                anchors.top: parent.top
                                anchors.left: parent.left
                                anchors.topMargin: 12
                                anchors.leftMargin: 12
                                width: Math.min(760, parent.width - 24)
                                height: 72
                                visible: root.exploreMode && gaussianView.ready
                                color: "#e5191c1e"
                                border.width: 1
                                border.color: Theme.borderStrong
                                radius: Theme.cornerPopup

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    spacing: 4

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 5
                                        Text {
                                            text: "DIAGNOSTIC VIEW"
                                            color: Theme.textSecondary
                                            font.family: Theme.uiFont
                                            font.pixelSize: 8
                                            font.weight: Font.DemiBold
                                        }
                                        TextButton {
                                            compact: true
                                            text: "Appearance"
                                            selected: root.visualizationMode === 0
                                            toolTip: "RGB Gaussian appearance (key 1). This is not collision geometry."
                                            onClicked: {
                                                root.visualizationMode = 0;
                                                gaussianView.forceActiveFocus();
                                            }
                                        }
                                        TextButton {
                                            compact: true
                                            text: "Depth"
                                            selected: root.visualizationMode === 1
                                            toolTip: "Relative inferred depth heat map (key 2). It is not LiDAR or metric depth."
                                            onClicked: {
                                                root.visualizationMode = 1;
                                                gaussianView.forceActiveFocus();
                                            }
                                        }
                                        TextButton {
                                            compact: true
                                            text: "Structure"
                                            selected: root.visualizationMode === 2
                                            toolTip: "Splat shortest-axis structure cue (key 3). It is not a certified surface normal."
                                            onClicked: {
                                                root.visualizationMode = 2;
                                                gaussianView.forceActiveFocus();
                                            }
                                        }
                                        TextButton {
                                            compact: true
                                            text: "Coverage"
                                            selected: root.visualizationMode === 3
                                            toolTip: "Opacity support and gaps (key 4). Dark means weak or missing evidence."
                                            onClicked: {
                                                root.visualizationMode = 3;
                                                gaussianView.forceActiveFocus();
                                            }
                                        }
                                        Item { Layout.fillWidth: true }
                                        Rectangle {
                                            visible: diagnosticPalette.width > 650
                                            implicitWidth: 128
                                            implicitHeight: 24
                                            color: "#3b292b"
                                            border.width: 1
                                            border.color: Theme.warning
                                            radius: Theme.cornerControl
                                            Text {
                                                anchors.centerIn: parent
                                                text: "NOT COLLISION READY"
                                                color: Theme.warning
                                                font.family: Theme.uiFont
                                                font.pixelSize: 8
                                                font.weight: Font.DemiBold
                                            }
                                        }
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: root.visualizationDescription(root.visualizationMode)
                                        color: Theme.textMuted
                                        font.family: Theme.uiFont
                                        font.pixelSize: 8
                                        elide: Text.ElideRight
                                    }
                                }
                            }

                            Rectangle {
                                z: 2
                                anchors.top: diagnosticPalette.visible
                                             ? diagnosticPalette.bottom : parent.top
                                anchors.left: parent.left
                                anchors.topMargin: diagnosticPalette.visible ? 8 : 12
                                anchors.leftMargin: 12
                                width: Math.min(520, parent.width - 24)
                                height: 42
                                visible: root.exploreMode && gaussianView.ready
                                         && root.hasSelection
                                         && String(root.selectedWorld.qualityTone) === "warning"
                                color: "#e5262116"
                                border.width: 1
                                border.color: Theme.warning
                                radius: Theme.cornerPopup

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10
                                    spacing: 8
                                    SvgIcon {
                                        source: Theme.icon("warning")
                                        iconSize: 15
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Experimental reconstruction / "
                                              + root.metricText(root.selectedWorld.psnr, 2) + " dB PSNR / "
                                              + root.metricText(root.selectedWorld.ssim, 3) + " SSIM. Gaps and unstable geometry are expected."
                                        color: Theme.textSecondary
                                        font.family: Theme.uiFont
                                        font.pixelSize: 9
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }

                            Rectangle {
                                z: 2
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.margins: 12
                                height: 52
                                visible: root.hasSelection && !root.exploreMode
                                color: "#e5191c1e"
                                border.width: 1
                                border.color: Theme.borderStrong
                                radius: Theme.cornerPopup

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 11
                                    anchors.rightMargin: 11
                                    spacing: 9
                                    SvgIcon {
                                        source: Theme.icon("info")
                                        iconSize: 15
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 1
                                        Text {
                                            text: "VALIDATION PREVIEW"
                                            color: Theme.textSecondary
                                            font.family: Theme.uiFont
                                            font.pixelSize: 8
                                            font.weight: Font.DemiBold
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: "The verified bundle is loaded. Choose Explore to enter the interactive Vulkan Gaussian world."
                                            color: Theme.textMuted
                                            font.family: Theme.uiFont
                                            font.pixelSize: 9
                                            elide: Text.ElideRight
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Panel {
                id: worldInspector
                visible: !Session.viewportFocusMode
                SplitView.preferredWidth: 320
                SplitView.minimumWidth: 270
                SplitView.maximumWidth: 560

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "World details"
                        subtitle: root.hasSelection ? "Local bundle" : "No selection"
                        iconSource: Theme.icon("inspector")
                        Layout.fillWidth: true
                    }

                    ScrollView {
                        id: inspectorScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        Column {
                            width: inspectorScroll.availableWidth

                            Section {
                                title: "Identity"
                                summary: root.hasSelection
                                         ? String(root.selectedWorld.displayName) : "—"

                                PropertyRow {
                                    label: "Name"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.displayName) : ""
                                        placeholderText: "No world"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Source"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.sourceSummary) : ""
                                        placeholderText: "Unavailable"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Created"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.createdText) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "World ID"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.worldId) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                            }

                            Section {
                                title: "Reconstruction"
                                summary: root.hasSelection
                                         ? String(root.selectedWorld.gaussianText) + " splats"
                                         : "—"

                                PropertyRow {
                                    label: "Profile"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.profileLabel) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Splats"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.gaussianText) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Type"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.representation) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Scale"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.scaleText) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                            }

                            Section {
                                title: "Quality"
                                summary: root.hasSelection
                                         ? String(root.selectedWorld.qualityLabel) : "—"

                                PropertyRow {
                                    label: "Tier"
                                    labelWidth: 82
                                    StatusBadge {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.qualityLabel) : "Unrated"
                                        tone: root.hasSelection
                                              ? String(root.selectedWorld.qualityTone) : "neutral"
                                    }
                                }
                                PropertyRow {
                                    label: "PSNR"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? root.metricText(root.selectedWorld.psnr, 2) + " dB"
                                              : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "SSIM"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? root.metricText(root.selectedWorld.ssim, 3) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                            }

                            Section {
                                title: "Storage"
                                summary: root.hasSelection
                                         ? String(root.selectedWorld.sizeText) : "—"

                                PropertyRow {
                                    label: "Job size"
                                    labelWidth: 82
                                    TextInput {
                                        text: root.hasSelection
                                              ? String(root.selectedWorld.sizeText) : ""
                                        placeholderText: "—"
                                        readOnly: true
                                    }
                                }
                                PropertyRow {
                                    label: "Location"
                                    labelWidth: 82
                                    TextButton {
                                        Layout.fillWidth: true
                                        text: "Open job folder"
                                        iconSource: Theme.icon("folder")
                                        enabled: root.hasSelection
                                        onClicked: WorldLibraryModel.openJobFolder(
                                                       String(root.selectedWorld.worldId))
                                    }
                                }
                            }

                            Section {
                                title: "Organize"

                                Item {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 44
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 12
                                        anchors.rightMargin: 12
                                        spacing: 7
                                        TextButton {
                                            Layout.fillWidth: true
                                            text: "Rename"
                                            iconSource: Theme.icon("edit")
                                            enabled: root.hasSelection && !WorldLibraryModel.busy
                                            onClicked: root.openRenameDialog()
                                        }
                                        TextButton {
                                            Layout.fillWidth: true
                                            text: "Delete"
                                            iconSource: Theme.icon("trash")
                                            tone: "danger"
                                            enabled: root.hasSelection && !WorldLibraryModel.busy
                                            onClicked: root.openDeleteDialog()
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Dialog {
        id: renameDialog

        property string worldId: ""

        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 420
        modal: true
        closePolicy: Popup.CloseOnEscape

        background: Rectangle {
            color: Theme.panel
            border.width: 1
            border.color: Theme.borderStrong
            radius: Theme.cornerPopup
        }

        header: Rectangle {
            implicitHeight: 42
            color: Theme.chrome
            border.width: 1
            border.color: Theme.borderSoft
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 13
                anchors.verticalCenter: parent.verticalCenter
                text: "Rename world"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }
        }

        contentItem: ColumnLayout {
            spacing: 8
            Text {
                Layout.fillWidth: true
                text: "Use a clear local name. The verified world manifest and reconstruction files are not modified."
                color: Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }
            TextInput {
                id: renameField
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.controlHeight
                maximumLength: 80
                placeholderText: "World name"
                onAccepted: {
                    if (WorldLibraryModel.renameWorld(renameDialog.worldId, text))
                        renameDialog.close();
                }
            }
        }

        footer: Rectangle {
            implicitHeight: 48
            color: Theme.chrome
            border.width: 1
            border.color: Theme.borderSoft
            RowLayout {
                anchors.fill: parent
                anchors.margins: 9
                spacing: 7
                Item { Layout.fillWidth: true }
                TextButton {
                    text: "Cancel"
                    onClicked: renameDialog.close()
                }
                TextButton {
                    text: "Save name"
                    tone: "primary"
                    enabled: renameField.text.trim().length > 0
                    onClicked: {
                        if (WorldLibraryModel.renameWorld(renameDialog.worldId,
                                                          renameField.text))
                            renameDialog.close();
                    }
                }
            }
        }
    }

    Dialog {
        id: deleteDialog

        property string worldId: ""
        property string worldName: ""
        property string storageText: ""

        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 460
        modal: true
        closePolicy: Popup.CloseOnEscape

        background: Rectangle {
            color: Theme.panel
            border.width: 1
            border.color: Theme.error
            radius: Theme.cornerPopup
        }

        header: Rectangle {
            implicitHeight: 42
            color: "#332123"
            border.width: 1
            border.color: Theme.error
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 8
                SvgIcon {
                    source: Theme.icon("warning")
                    iconSize: 16
                }
                Text {
                    text: "Permanently delete world?"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }
        }

        contentItem: ColumnLayout {
            spacing: 10
            Text {
                Layout.fillWidth: true
                text: "Delete “" + deleteDialog.worldName + "” and recover approximately "
                      + deleteDialog.storageText + "?"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 11
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                text: "This removes the published bundle, extracted frames, camera solution, training checkpoints, validation renders, and logs for this job. This cannot be undone."
                color: Theme.textMuted
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.WordWrap
                lineHeight: 1.2
            }
        }

        footer: Rectangle {
            implicitHeight: 48
            color: Theme.chrome
            border.width: 1
            border.color: Theme.borderSoft
            RowLayout {
                anchors.fill: parent
                anchors.margins: 9
                spacing: 7
                Item { Layout.fillWidth: true }
                TextButton {
                    text: "Cancel"
                    onClicked: deleteDialog.close()
                }
                TextButton {
                    text: "Delete permanently"
                    iconSource: Theme.icon("trash")
                    tone: "danger"
                    onClicked: {
                        if (WorldLibraryModel.deleteWorld(deleteDialog.worldId))
                            deleteDialog.close();
                    }
                }
            }
        }
    }
}
