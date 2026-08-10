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

find_package(Python3 3.11 REQUIRED COMPONENTS Interpreter)
add_test(
    NAME ReconstructionWorkerTests
    COMMAND ${Python3_EXECUTABLE} -m unittest discover
            -s ${CMAKE_CURRENT_SOURCE_DIR}/python
            -p test_reconstruction_worker.py
)
