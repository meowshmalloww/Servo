cmake_minimum_required(VERSION 3.16)

project(Servo VERSION 0.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(GNUInstallDirs)

find_package(Qt6 REQUIRED COMPONENTS Quick QuickControls2)

qt_standard_project_setup(REQUIRES 6.10)

# Content of downloaded design from Figma to Qt or similar
if (EXISTS "${CMAKE_CURRENT_LIST_DIR}/importedcontent/CMakeLists.txt")
    add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/importedcontent)
endif()

qt_add_executable(appServo
    main.cpp
)

set_source_files_properties(Theme.qml PROPERTIES
    QT_QML_SINGLETON_TYPE TRUE
)

qt_add_qml_module(appServo
    URI Servo
    QML_FILES
        Main.qml
        Theme.qml
        AppButton.qml
        IconButton.qml
        WorkspaceTab.qml
        PanelFrame.qml
        PanelHeader.qml
        PaneDivider.qml
        ServoSearchField.qml
        TreeRow.qml
        PropertyRow.qml
        UiTextField.qml
        UiComboBox.qml
        ConfigSection.qml
        StatusDot.qml
        MetricPlot.qml
        EngineViewport.qml
        TimelinePanel.qml
        ActivityRail.qml
        PrepareWorkspace.qml
        SimulateWorkspace.qml
        DiagnoseWorkspace.qml
        TrainWorkspace.qml
        VerifyWorkspace.qml
    RESOURCES
        docs/ui-redesign-v2/02-simulate-workspace.png
)

# Qt for iOS sets MACOSX_BUNDLE_GUI_IDENTIFIER automatically since Qt 6.1.
# If you are developing for iOS or macOS you should consider setting an
# explicit, fixed bundle identifier manually though.
set_target_properties(appServo PROPERTIES
#    MACOSX_BUNDLE_GUI_IDENTIFIER com.example.appServo
    MACOSX_BUNDLE_BUNDLE_VERSION ${PROJECT_VERSION}
    MACOSX_BUNDLE_SHORT_VERSION_STRING ${PROJECT_VERSION_MAJOR}.${PROJECT_VERSION_MINOR}
    MACOSX_BUNDLE TRUE
    WIN32_EXECUTABLE TRUE
)

target_link_libraries(appServo
    PRIVATE
        Qt6::Quick
        Qt6::QuickControls2
)

install(TARGETS appServo
    BUNDLE DESTINATION .
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)
