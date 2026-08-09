pragma Singleton

import QtQuick

QtObject {
    property url projectUrl: ""
    property url recordingUrl: ""
    property int workspaceIndex: 0

    property var projectTreeModel: null
    property var worldModel: null
    property var runModel: null
    property var failureModel: null
    property var experimentModel: null
    property var trainingJobModel: null
    property var checkpointModel: null
    property var capabilityModel: null

    readonly property bool projectOpen: projectUrl.toString().length > 0
    readonly property bool recordingSelected: recordingUrl.toString().length > 0
    readonly property string projectName: fileStem(projectUrl)
    readonly property string recordingName: fileName(recordingUrl)
    readonly property int maximumUiFrameRate: 120

    signal openProjectRequested()
    signal importRecordingRequested()

    function fileName(url) {
        const value = decodeURIComponent(url.toString())
        return value.length > 0 ? value.substring(value.lastIndexOf("/") + 1) : ""
    }

    function fileStem(url) {
        const name = fileName(url)
        const dot = name.lastIndexOf(".")
        return dot > 0 ? name.substring(0, dot) : name
    }

    function closeProject() {
        projectUrl = ""
        recordingUrl = ""
        projectTreeModel = null
        worldModel = null
        runModel = null
        failureModel = null
        experimentModel = null
        trainingJobModel = null
        checkpointModel = null
        capabilityModel = null
    }
}
