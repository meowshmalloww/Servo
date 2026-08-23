pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import "../components"

Item {
    id: root

    property string selectedProfile: {
        if (profileField.currentIndex < 0
                || profileField.currentIndex >= ReconstructionController.profileNames.length)
            return "balanced-12gb";
        return ReconstructionController.profileNames[profileField.currentIndex];
    }
    readonly property var reconstructionStages: [
        { "id": "hash", "label": "Sources" },
        { "id": "extract", "label": "Frames" },
        { "id": "pose", "label": "Camera solve" },
        { "id": "geometry", "label": "Road geometry" },
        { "id": "train", "label": "Gaussian fit" },
        { "id": "validate", "label": "Quality gate" },
        { "id": "publish", "label": "Publish" }
    ]

    function stageIndex(stageId) {
        for (let index = 0; index < reconstructionStages.length; ++index) {
            if (reconstructionStages[index].id === stageId)
                return index;
        }
        return -1;
    }

    function stageTone(index) {
        if (ReconstructionController.state === "complete")
            return "success";
        const current = stageIndex(ReconstructionController.stage);
        if (current < 0)
            return "neutral";
        if (index < current)
            return "success";
        if (index > current)
            return "neutral";
        if (ReconstructionController.state === "failed")
            return "error";
        if (ReconstructionController.state === "cancelled")
            return "warning";
        return "info";
    }

    function addDroppedUrls(urls) {
        const values = [];
        for (let index = 0; index < urls.length; ++index)
            values.push(urls[index]);
        MediaSourceModel.addUrls(values);
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PageToolbar {
            title: "Create World"
            subtitle: "Turn observed image and video media into a validated 3D Gaussian world"
            iconSource: Theme.icon("build")
            Layout.fillWidth: true

            Text {
                visible: MediaSourceModel.busy
                text: MediaSourceModel.activityText
                color: Theme.info
                font.family: Theme.uiFont
                font.pixelSize: 10
            }

            Text {
                visible: ReconstructionController.state === "running"
                         || ReconstructionController.state === "cancelling"
                text: ReconstructionController.message
                color: Theme.info
                font.family: Theme.uiFont
                font.pixelSize: 10
                elide: Text.ElideRight
                Layout.maximumWidth: 280
            }

            TextButton {
                text: "Add files"
                iconSource: Theme.icon("plus")
                tone: "primary"
                enabled: !ReconstructionController.running
                onClicked: mediaFileDialog.open()
            }

            TextButton {
                text: "Add folder"
                iconSource: Theme.icon("folder")
                enabled: !ReconstructionController.running
                onClicked: mediaFolderDialog.open()
            }
        }

        Rectangle {
            visible: MediaSourceModel.lastError.length > 0
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 36 : 0
            color: "#332426"
            border.width: 1
            border.color: Theme.error

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 5
                spacing: 8

                SvgIcon {
                    source: Theme.icon("error")
                    iconSize: 14
                }

                Text {
                    Layout.fillWidth: true
                    text: MediaSourceModel.lastError
                    color: Theme.textSecondary
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }

                IconButton {
                    iconSource: Theme.icon("close")
                    toolTip: "Dismiss"
                    buttonSize: 25
                    onClicked: MediaSourceModel.clearLastError()
                }
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            handle: SplitHandle {}

            Panel {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 620

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Source media"
                        subtitle: MediaSourceModel.count === 0
                                  ? "No application-imposed file-size or duration limit"
                                  : MediaSourceModel.readyCount + " of " + MediaSourceModel.count + " ready"
                        iconSource: Theme.icon("camera")
                        Layout.fillWidth: true
                    }

                    ScrollView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 224
                        clip: true
                        contentWidth: availableWidth

                        SourceDropZone {
                            width: Math.max(0, parent.width - 24)
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.top: parent.top
                            anchors.topMargin: 12
                            enabled: !ReconstructionController.running

                            onAddFilesRequested: mediaFileDialog.open()
                            onAddFolderRequested: mediaFolderDialog.open()
                            onUrlsDropped: function(urls) { root.addDroppedUrls(urls); }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 42
                        color: Theme.panelRaised
                        border.width: 1
                        border.color: Theme.borderSoft

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            spacing: 13

                            MetricReadout {
                                label: "SOURCES"
                                value: MediaSourceModel.count
                                toolTip: "Unique source paths registered in the local catalog"
                            }

                            Rectangle {
                                Layout.preferredWidth: 1
                                Layout.preferredHeight: 18
                                color: Theme.border
                            }

                            MetricReadout {
                                label: "READY"
                                value: MediaSourceModel.readyCount
                                toolTip: "Sources with successfully parsed image or video metadata"
                            }

                            Rectangle {
                                Layout.preferredWidth: 1
                                Layout.preferredHeight: 18
                                color: Theme.border
                            }

                            MetricReadout {
                                label: "ERRORS"
                                value: MediaSourceModel.errorCount
                                toolTip: "Missing, corrupt, unsupported, or unreadable sources"
                            }

                            Rectangle {
                                Layout.preferredWidth: 1
                                Layout.preferredHeight: 18
                                color: Theme.border
                            }

                            MetricReadout {
                                label: "ORIGINAL SIZE"
                                value: MediaSourceModel.totalBytesText
                                toolTip: "Aggregate original source bytes. Registration does not copy the files."
                            }

                            Item { Layout.fillWidth: true }

                            Text {
                                visible: MediaSourceModel.busy
                                text: MediaSourceModel.activityText
                                color: Theme.info
                                font.family: Theme.uiFont
                                font.pixelSize: 9
                            }
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        ListView {
                            id: sourceList
                            anchors.fill: parent
                            clip: true
                            model: MediaSourceModel
                            reuseItems: true
                            boundsBehavior: Flickable.StopAtBounds
                            interactive: !ReconstructionController.running

                            delegate: MediaSourceDelegate {
                                width: sourceList.width
                                enabled: !ReconstructionController.running
                                onRetryRequested: function(row) { MediaSourceModel.retry(row); }
                                onRemoveRequested: function(row) { MediaSourceModel.removeReference(row); }
                            }

                            ScrollBar.vertical: ScrollBar {
                                policy: ScrollBar.AsNeeded
                            }
                        }

                        EmptyState {
                            anchors.centerIn: parent
                            width: Math.min(440, parent.width - 40)
                            visible: MediaSourceModel.count === 0
                            iconSource: Theme.icon("camera")
                            title: "No reconstruction sources"
                            description: "Add overlapping images or a mostly static video with useful camera translation. Metadata appears here without decoding the complete source."
                        }
                    }
                }
            }

            Panel {
                SplitView.preferredWidth: 382
                SplitView.minimumWidth: 340
                SplitView.maximumWidth: 470

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    PanelHeader {
                        title: "Build observed world"
                        subtitle: "Media → Gaussian world"
                        iconSource: Theme.icon("world")
                        Layout.fillWidth: true
                    }

                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth

                        ColumnLayout {
                            width: Math.max(0, parent.width - 18)
                            spacing: 10

                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.leftMargin: 12
                                Layout.rightMargin: 12
                                Layout.topMargin: 12
                                spacing: 7

                                Text {
                                    text: "World name"
                                    color: Theme.textMuted
                                    font.family: Theme.uiFont
                                    font.pixelSize: 9
                                }

                                TextInput {
                                    id: worldNameField
                                    Layout.fillWidth: true
                                    text: "Observed world"
                                    placeholderText: "World name"
                                    enabled: !ReconstructionController.running
                                }

                                Text {
                                    text: "Quality and resource profile"
                                    color: Theme.textMuted
                                    font.family: Theme.uiFont
                                    font.pixelSize: 9
                                }

                                SelectField {
                                    id: profileField
                                    Layout.fillWidth: true
                                    model: ReconstructionController.profileLabels
                                    currentIndex: 0
                                    enabled: !ReconstructionController.running
                                }

                                RowLayout {
                                    Layout.fillWidth: true

                                    Text {
                                        text: ReconstructionController.estimatedStorageText(
                                                  MediaSourceModel.readyBytes,
                                                  root.selectedProfile)
                                        color: Theme.textSecondary
                                        font.family: Theme.monoFont
                                        font.pixelSize: 9
                                    }

                                    Item { Layout.fillWidth: true }

                                    Text {
                                        text: ReconstructionController.expectedVramGiB(
                                                  root.selectedProfile).toFixed(1) + " GiB VRAM target"
                                        color: Theme.textMuted
                                        font.family: Theme.monoFont
                                        font.pixelSize: 9
                                    }
                                }
                            }

                            Section {
                                Layout.fillWidth: true
                                Layout.leftMargin: 12
                                Layout.rightMargin: 12
                                title: "Reconstruction method"
                                summary: "Geometry + 3DGS optimization"
                                expanded: false

                                PropertyRow {
                                    label: "Camera recovery"
                                    Text {
                                        text: "Multi-view geometry"
                                        color: Theme.textSecondary
                                        font.family: Theme.uiFont
                                        font.pixelSize: 9
                                    }
                                }

                                PropertyRow {
                                    label: "Scene representation"
                                    Text {
                                        text: "Optimized 3D Gaussians"
                                        color: Theme.textSecondary
                                        font.family: Theme.uiFont
                                        font.pixelSize: 9
                                    }
                                }

                                PropertyRow {
                                    label: "Interactive display"
                                    Text {
                                        text: "Vulkan"
                                        color: Theme.textSecondary
                                        font.family: Theme.monoFont
                                        font.pixelSize: 9
                                    }
                                }

                                Text {
                                    Layout.fillWidth: true
                                    Layout.margins: 8
                                    text: "This is not an LLM. Servo solves cameras, then optimizes an explicit Gaussian scene from the observed pixels."
                                    color: Theme.textMuted
                                    font.family: Theme.uiFont
                                    font.pixelSize: 9
                                    wrapMode: Text.WordWrap
                                }
                            }

                            Section {
                                Layout.fillWidth: true
                                Layout.leftMargin: 12
                                Layout.rightMargin: 12
                                title: "Native runtime"
                                summary: ReconstructionController.state === "checking"
                                         ? "Verifying CUDA kernel"
                                         : (ReconstructionController.ready ? "Ready" : "Blocked")
                                expanded: !ReconstructionController.ready

                                PropertyRow {
                                    label: "Qt Quick Vulkan backend"
                                    StatusBadge {
                                        text: RuntimeMetrics.vulkanReady ? "Ready" : "Checking"
                                        tone: RuntimeMetrics.vulkanReady ? "success" : "info"
                                    }
                                }

                                Repeater {
                                    model: ReconstructionController.dependencies

                                    delegate: PropertyRow {
                                        id: dependencyRow
                                        required property var modelData
                                        label: modelData.name || "Dependency"

                                        StatusBadge {
                                            text: dependencyRow.modelData.ready
                                                  ? (dependencyRow.modelData.version || "Ready")
                                                  : "Missing"
                                            tone: dependencyRow.modelData.ready ? "success" : "error"
                                        }
                                    }
                                }

                                PropertyRow {
                                    label: "Free workspace"
                                    Text {
                                        text: ReconstructionController.freeSpaceText.length > 0
                                              ? ReconstructionController.freeSpaceText : "—"
                                        color: Theme.textSecondary
                                        font.family: Theme.monoFont
                                        font.pixelSize: 9
                                    }
                                }

                                TextButton {
                                    Layout.fillWidth: true
                                    Layout.margins: 7
                                    text: "Run preflight again"
                                    iconSource: Theme.icon("refresh")
                                    enabled: !ReconstructionController.running
                                    onClicked: ReconstructionController.refreshPreflight()
                                }
                            }

                            Section {
                                Layout.fillWidth: true
                                Layout.leftMargin: 12
                                Layout.rightMargin: 12
                                title: "Capture gate"
                                summary: MediaSourceModel.readyCount + " ready"

                                PropertyRow {
                                    label: "Sources"
                                    StatusBadge {
                                        text: MediaSourceModel.readyCount > 0
                                              ? MediaSourceModel.readyCount + " ready" : "Add media"
                                        tone: MediaSourceModel.readyCount > 0 ? "success" : "warning"
                                    }
                                }

                                Text {
                                    Layout.fillWidth: true
                                    Layout.margins: 8
                                    text: "Walk the camera through the scene with steady translation and strong overlap. Keep zoom fixed and moving people, cars, reflections, sky, water, and motion blur to a minimum. Pure rotation is not enough for depth."
                                    color: Theme.textMuted
                                    font.family: Theme.uiFont
                                    font.pixelSize: 9
                                    wrapMode: Text.WordWrap
                                }

                                Text {
                                    Layout.fillWidth: true
                                    Layout.leftMargin: 8
                                    Layout.rightMargin: 8
                                    Layout.bottomMargin: 8
                                    text: "Monocular scale is unknown until you provide a known measurement. Unseen surfaces are not invented, and a Gaussian scene is not collision geometry."
                                    color: Theme.warning
                                    font.family: Theme.uiFont
                                    font.pixelSize: 9
                                    wrapMode: Text.WordWrap
                                }
                            }

                            Section {
                                visible: ReconstructionController.jobPath.length > 0
                                Layout.fillWidth: true
                                Layout.leftMargin: 12
                                Layout.rightMargin: 12
                                title: "Current job"
                                summary: ReconstructionController.state
                                expanded: true

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.margins: 8
                                    spacing: 6

                                    RowLayout {
                                        Layout.fillWidth: true

                                        StatusBadge {
                                            text: ReconstructionController.stage.length > 0
                                                  ? ReconstructionController.stage : ReconstructionController.state
                                            tone: ReconstructionController.state === "complete" ? "success"
                                                  : (ReconstructionController.state === "failed" ? "error"
                                                     : (ReconstructionController.state === "cancelled" ? "warning" : "info"))
                                        }

                                        Text {
                                            Layout.fillWidth: true
                                            text: ReconstructionController.message
                                            color: Theme.textSecondary
                                            font.family: Theme.uiFont
                                            font.pixelSize: 10
                                            elide: Text.ElideRight
                                        }
                                    }

                                    GridLayout {
                                        Layout.fillWidth: true
                                        columns: 3
                                        rowSpacing: 5
                                        columnSpacing: 5

                                        Repeater {
                                            model: root.reconstructionStages

                                            delegate: Rectangle {
                                                id: phaseChip
                                                required property var modelData
                                                required property int index
                                                readonly property string phaseTone: root.stageTone(index)
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 25
                                                color: phaseTone === "success" ? "#263529"
                                                     : (phaseTone === "info" ? Theme.selection
                                                        : (phaseTone === "warning" ? "#3a3022"
                                                           : (phaseTone === "error" ? "#382628"
                                                              : Theme.field)))
                                                border.width: 1
                                                border.color: phaseTone === "success" ? Theme.success
                                                              : (phaseTone === "info" ? Theme.selectionBorder
                                                                 : (phaseTone === "warning" ? Theme.warning
                                                                    : (phaseTone === "error" ? Theme.error
                                                                       : Theme.borderSoft)))
                                                radius: Theme.cornerControl

                                                RowLayout {
                                                    anchors.fill: parent
                                                    anchors.leftMargin: 7
                                                    anchors.rightMargin: 6
                                                    spacing: 5

                                                    Rectangle {
                                                        Layout.preferredWidth: 6
                                                        Layout.preferredHeight: 6
                                                        radius: 3
                                                        color: phaseChip.phaseTone === "success" ? Theme.success
                                                             : (phaseChip.phaseTone === "info" ? Theme.info
                                                                : (phaseChip.phaseTone === "warning" ? Theme.warning
                                                                   : (phaseChip.phaseTone === "error" ? Theme.error
                                                                      : Theme.textDisabled)))
                                                    }

                                                    Text {
                                                        Layout.fillWidth: true
                                                        text: phaseChip.modelData.label
                                                        color: phaseChip.phaseTone === "neutral"
                                                               ? Theme.textMuted : Theme.textSecondary
                                                        font.family: Theme.uiFont
                                                        font.pixelSize: 8
                                                        elide: Text.ElideRight
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 6
                                        color: Theme.field
                                        border.width: 1
                                        border.color: Theme.border

                                        Rectangle {
                                            visible: ReconstructionController.progress >= 0
                                            width: parent.width * Math.max(0, Math.min(1,
                                                   ReconstructionController.progress))
                                            height: parent.height
                                            color: ReconstructionController.state === "failed"
                                                   ? Theme.error : Theme.accent
                                        }
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: ReconstructionController.progressText
                                        color: Theme.textMuted
                                        font.family: Theme.monoFont
                                        font.pixelSize: 9
                                        elide: Text.ElideRight
                                    }

                                    Text {
                                        visible: ReconstructionController.details.length > 0
                                        Layout.fillWidth: true
                                        text: ReconstructionController.details
                                        color: ReconstructionController.state === "failed"
                                               ? Theme.error : Theme.textMuted
                                        font.family: Theme.uiFont
                                        font.pixelSize: 9
                                        wrapMode: Text.WordWrap
                                    }

                                    Rectangle {
                                        visible: ReconstructionController.recentLog.length > 0
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: visible ? 92 : 0
                                        color: Theme.field
                                        border.width: 1
                                        border.color: Theme.borderSoft

                                        ScrollView {
                                            anchors.fill: parent
                                            anchors.margins: 6
                                            clip: true

                                            Text {
                                                width: parent.width
                                                text: ReconstructionController.recentLog
                                                color: Theme.textDisabled
                                                font.family: Theme.monoFont
                                                font.pixelSize: 8
                                                wrapMode: Text.WrapAnywhere
                                            }
                                        }
                                    }

                                    RowLayout {
                                        Layout.fillWidth: true

                                        TextButton {
                                            text: "Job folder"
                                            iconSource: Theme.icon("folder")
                                            onClicked: ReconstructionController.openJobFolder()
                                        }

                                        TextButton {
                                            visible: ReconstructionController.worldPath.length > 0
                                            text: "View in Worlds"
                                            iconSource: Theme.icon("world")
                                            tone: "primary"
                                            onClicked: {
                                                WorldLibraryModel.selectWorldPath(
                                                    ReconstructionController.worldPath);
                                                Session.workspaceIndex = 1;
                                            }
                                        }

                                        Item { Layout.fillWidth: true }
                                    }
                                }
                            }

                            Item { Layout.preferredHeight: 4 }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        color: Theme.borderSoft
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.margins: 12
                        spacing: 7

                        TextButton {
                            visible: ReconstructionController.canCancel
                            text: "Cancel safely"
                            iconSource: Theme.icon("stop")
                            tone: "danger"
                            onClicked: ReconstructionController.cancel()
                        }

                        TextButton {
                            visible: ReconstructionController.canRetry
                            text: "Retry / resume"
                            iconSource: Theme.icon("refresh")
                            onClicked: ReconstructionController.retry()
                        }

                        TextButton {
                            Layout.fillWidth: true
                            text: ReconstructionController.state === "complete"
                                  ? "Build another world" : "Build world"
                            iconSource: Theme.icon("build")
                            tone: "primary"
                            enabled: ReconstructionController.ready
                                     && RuntimeMetrics.vulkanReady
                                     && MediaSourceModel.readyCount > 0
                                     && ReconstructionController.capacityReady(
                                            MediaSourceModel.readyBytes,
                                            root.selectedProfile)
                                     && !MediaSourceModel.busy
                            toolTip: !ReconstructionController.ready
                                     ? "The real native CUDA/COLMAP/gsplat preflight must pass"
                                     : (MediaSourceModel.readyCount === 0
                                        ? "Add at least one ready image or video source"
                                        : (!ReconstructionController.capacityReady(
                                               MediaSourceModel.readyBytes,
                                               root.selectedProfile)
                                           ? ReconstructionController.capacityIssue(
                                                 MediaSourceModel.readyBytes,
                                                 root.selectedProfile)
                                           : "Create a durable local Gaussian reconstruction job"))
                            onClicked: ReconstructionController.start(
                                           MediaSourceModel.readySources(),
                                           root.selectedProfile,
                                           worldNameField.text)
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.leftMargin: 12
                        Layout.rightMargin: 12
                        Layout.bottomMargin: 10
                        text: ReconstructionController.ready
                              ? "Build streams media, validates camera recovery, checkpoints training, and publishes only a verified PLY bundle."
                              : ReconstructionController.message
                        color: ReconstructionController.state === "blocked"
                               ? Theme.error : Theme.textMuted
                        font.family: Theme.uiFont
                        font.pixelSize: 8
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }

    FileDialog {
        id: mediaFileDialog
        title: "Add reconstruction sources"
        fileMode: FileDialog.OpenFiles
        nameFilters: [
            "Images and video (*.jpg *.jpeg *.png *.tif *.tiff *.webp *.heic *.heif *.avif *.bmp *.dng *.exr *.hdr *.mp4 *.mov *.m4v *.mkv *.avi *.webm *.mts *.m2ts *.ts *.mxf *.mpg *.mpeg *.3gp *.wmv *.ogv)",
            "All files (*)"
        ]
        onAccepted: root.addDroppedUrls(selectedFiles)
    }

    FolderDialog {
        id: mediaFolderDialog
        title: "Add a folder of reconstruction sources"
        onAccepted: MediaSourceModel.addUrl(selectedFolder)
    }
}
