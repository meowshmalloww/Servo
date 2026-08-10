set_source_files_properties(
    Theme.qml
    Session.qml
    PROPERTIES QT_QML_SINGLETON_TYPE TRUE
)

qt_add_executable(appServo WIN32
    ../app/main.cpp
)

if(WIN32)
    target_sources(appServo PRIVATE
        ../app/servo.rc
    )
endif()

qt_add_qml_module(appServo
    URI Servo
    VERSION 1.0

    QML_FILES
        Main.qml
        Theme.qml
        Session.qml

        components/BottomDrawer.qml
        components/DataTable.qml
        components/EmptyState.qml
        components/EditorMenu.qml
        components/EditorMenuItem.qml
        components/EditorMenuSeparator.qml
        components/EntityList.qml
        components/IconButton.qml
        components/LinePlot.qml
        components/MediaSourceDelegate.qml
        components/MetricReadout.qml
        components/PageToolbar.qml
        components/Panel.qml
        components/PanelHeader.qml
        components/PropertyRow.qml
        components/SearchField.qml
        components/Section.qml
        components/SelectField.qml
        components/SettingsDialog.qml
        components/SplitHandle.qml
        components/StatusBadge.qml
        components/SourceDropZone.qml
        components/SvgIcon.qml
        components/TextButton.qml
        components/TextInput.qml
        components/Timeline.qml
        components/TopTab.qml
        components/ViewportSurface.qml

        workspaces/CapabilitiesWorkspace.qml
        workspaces/DiagnoseWorkspace.qml
        workspaces/PrepareWorkspace.qml
        workspaces/RunsWorkspace.qml
        workspaces/TrainWorkspace.qml
        workspaces/VerifyWorkspace.qml
        workspaces/WorldsWorkspace.qml

    SOURCES
        media/MediaSourceModel.cpp
        media/MediaSourceModel.h
        reconstruction/ReconstructionController.cpp
        reconstruction/ReconstructionController.h
        rendering/LinePlotItem.cpp
        rendering/LinePlotItem.h
        runtime/RuntimeMetrics.cpp
        runtime/RuntimeMetrics.h

    RESOURCES
        assets/servo-logo.png
        icons/app.svg
        icons/back.svg
        icons/build.svg
        icons/camera.svg
        icons/capability.svg
        icons/chart.svg
        icons/check.svg
        icons/chevron-down.svg
        icons/chevron-right.svg
        icons/close.svg
        icons/cube.svg
        icons/diagnose.svg
        icons/error.svg
        icons/export.svg
        icons/file.svg
        icons/filter.svg
        icons/focus.svg
        icons/folder.svg
        icons/forward.svg
        icons/grid.svg
        icons/info.svg
        icons/inspector.svg
        icons/maximize.svg
        icons/minimize.svg
        icons/more.svg
        icons/orbit.svg
        icons/open.svg
        icons/pause.svg
        icons/play.svg
        icons/plus.svg
        icons/project.svg
        icons/resize-horizontal.svg
        icons/resize-vertical.svg
        icons/refresh.svg
        icons/run.svg
        icons/search.svg
        icons/select.svg
        icons/sensor.svg
        icons/settings.svg
        icons/stop.svg
        icons/table.svg
        icons/terminal.svg
        icons/train.svg
        icons/verify.svg
        icons/warning.svg
        icons/world.svg
)

target_include_directories(appServo PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/media
    ${CMAKE_CURRENT_SOURCE_DIR}/reconstruction
    ${CMAKE_CURRENT_SOURCE_DIR}/rendering
    ${CMAKE_CURRENT_SOURCE_DIR}/runtime
)

target_compile_definitions(appServo PRIVATE
    SERVO_RECONSTRUCTION_SOURCE_DIR="${CMAKE_SOURCE_DIR}/tools/reconstruction"
)

target_link_libraries(appServo
    PRIVATE
        Qt6::Concurrent
        Qt6::GuiPrivate
        Qt6::Quick
        Qt6::Quick3D
        Qt6::QuickControls2
        Qt6::QuickDialogs2
        Qt6::Svg
)

if(WIN32)
    target_link_libraries(appServo PRIVATE dwmapi psapi)
endif()

install(DIRECTORY ${CMAKE_SOURCE_DIR}/tools/reconstruction/
    DESTINATION reconstruction
    FILES_MATCHING
        PATTERN "*.py"
        PATTERN "*.json"
        PATTERN "*.txt"
        PATTERN "*.ps1"
)
