cmake_minimum_required(VERSION 3.21)

project(Servo VERSION 0.2.0 LANGUAGES CXX)

# Single-configuration generators otherwise default to an unoptimized binary
# when CMAKE_BUILD_TYPE is omitted. Keep developer overrides intact.
if(NOT CMAKE_CONFIGURATION_TYPES AND NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
    set_property(CACHE CMAKE_BUILD_TYPE PROPERTY STRINGS Debug Release RelWithDebInfo MinSizeRel)
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(GNUInstallDirs)
include(CTest)

find_package(Qt6 6.11 REQUIRED COMPONENTS
    Concurrent
    GuiPrivate
    Multimedia
    Network
    Quick
    Quick3D
    QuickControls2
    QuickDialogs2
    ShaderTools
    Sql
    Svg
)

qt_standard_project_setup(REQUIRES 6.11)

add_subdirectory(src/ui)

if(BUILD_TESTING)
    find_package(Qt6 6.11 REQUIRED COMPONENTS Test)
    add_subdirectory(tests)
endif()

set_target_properties(appServo PROPERTIES
    MACOSX_BUNDLE TRUE
    MACOSX_BUNDLE_BUNDLE_VERSION ${PROJECT_VERSION}
    MACOSX_BUNDLE_SHORT_VERSION_STRING ${PROJECT_VERSION_MAJOR}.${PROJECT_VERSION_MINOR}
)

install(TARGETS appServo
    BUNDLE DESTINATION .
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)

# Package the Qt/QML runtime used by the desktop application.  A plain copy of
# appServo.exe is not sufficient on Windows because Quick 3D also needs its
# import plugins and Assimp runtime.  Keep deployment tied to CMake's resolved
# Qt installation so release bundles cannot silently mix Qt versions.
qt_generate_deploy_qml_app_script(
    TARGET appServo
    OUTPUT_SCRIPT servo_deploy_script
    NO_UNSUPPORTED_PLATFORM_ERROR
)
install(SCRIPT ${servo_deploy_script})
