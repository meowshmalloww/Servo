qt_add_executable(MediaSourceModelTests
    MediaSourceModelTests.cpp
    ../src/ui/media/MediaSourceModel.cpp
    ../src/ui/media/MediaSourceModel.h
)

target_include_directories(MediaSourceModelTests PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../src/ui/media
)

target_link_libraries(MediaSourceModelTests
    PRIVATE
        Qt6::Concurrent
        Qt6::Gui
        Qt6::Qml
        Qt6::Test
)

add_test(NAME MediaSourceModelTests COMMAND MediaSourceModelTests)

qt_add_executable(ReconstructionControllerTests
    ReconstructionControllerTests.cpp
    ../src/ui/reconstruction/ReconstructionController.cpp
    ../src/ui/reconstruction/ReconstructionController.h
)

target_include_directories(ReconstructionControllerTests PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../src/ui/reconstruction
)

target_compile_definitions(ReconstructionControllerTests PRIVATE
    SERVO_RECONSTRUCTION_SOURCE_DIR="${CMAKE_SOURCE_DIR}/tools/reconstruction"
)

target_link_libraries(ReconstructionControllerTests
    PRIVATE
        Qt6::Concurrent
        Qt6::Gui
        Qt6::Qml
        Qt6::Test
)

add_test(NAME ReconstructionControllerTests COMMAND ReconstructionControllerTests)

qt_add_executable(WorldLibraryModelTests
    WorldLibraryModelTests.cpp
    ../src/ui/worlds/WorldLibraryModel.cpp
    ../src/ui/worlds/WorldLibraryModel.h
)

target_include_directories(WorldLibraryModelTests PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../src/ui/worlds
)

target_link_libraries(WorldLibraryModelTests
    PRIVATE
        Qt6::Concurrent
        Qt6::Gui
        Qt6::Qml
        Qt6::Test
)

add_test(NAME WorldLibraryModelTests COMMAND WorldLibraryModelTests)

qt_add_executable(GaussianPathSmoothingTests
    GaussianPathSmoothingTests.cpp
    ../src/ui/rendering/GaussianPathSmoothing.cpp
    ../src/ui/rendering/GaussianPathSmoothing.h
)

target_include_directories(GaussianPathSmoothingTests PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../src/ui/rendering
)

target_link_libraries(GaussianPathSmoothingTests
    PRIVATE
        Qt6::Gui
        Qt6::Test
)

add_test(NAME GaussianPathSmoothingTests COMMAND GaussianPathSmoothingTests)

qt_add_executable(GaussianSortStabilityTests
    GaussianSortStabilityTests.cpp
)

target_compile_definitions(GaussianSortStabilityTests PRIVATE
    SERVO_GAUSSIAN_PREPROCESS_SHADER="${CMAKE_SOURCE_DIR}/src/ui/rendering/shaders/gaussian_preprocess.comp"
)

target_link_libraries(GaussianSortStabilityTests
    PRIVATE
        Qt6::Gui
        Qt6::Test
)

add_test(NAME GaussianSortStabilityTests COMMAND GaussianSortStabilityTests)

qt_add_executable(GaussianWorldEnvironmentTests
    GaussianWorldEnvironmentTests.cpp
    ../src/ui/rendering/GaussianSplatView.cpp
    ../src/ui/rendering/GaussianSplatView.h
    ../src/ui/rendering/GaussianPathSmoothing.cpp
    ../src/ui/rendering/GaussianPathSmoothing.h
)

target_include_directories(GaussianWorldEnvironmentTests PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../src/ui/rendering
)

target_link_libraries(GaussianWorldEnvironmentTests
    PRIVATE
        Qt6::Concurrent
        Qt6::GuiPrivate
        Qt6::Quick
        Qt6::Test
)

add_test(NAME GaussianWorldEnvironmentTests COMMAND GaussianWorldEnvironmentTests)

find_package(Python3 3.11 REQUIRED COMPONENTS Interpreter)
add_test(
    NAME ReconstructionWorkerTests
    COMMAND ${Python3_EXECUTABLE} -m unittest discover
            -s ${CMAKE_CURRENT_SOURCE_DIR}/python
            -p test_reconstruction_worker.py
)

add_test(
    NAME ReconstructionReleaseContractTests
    COMMAND ${Python3_EXECUTABLE} -m unittest discover
            -s ${CMAKE_CURRENT_SOURCE_DIR}/python
            -p test_reconstruction_release.py
)
