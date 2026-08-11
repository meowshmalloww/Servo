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

find_package(Python3 3.11 REQUIRED COMPONENTS Interpreter)
add_test(
    NAME ReconstructionWorkerTests
    COMMAND ${Python3_EXECUTABLE} -m unittest discover
            -s ${CMAKE_CURRENT_SOURCE_DIR}/python
            -p test_reconstruction_worker.py
)
