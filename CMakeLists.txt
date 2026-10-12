
cmake_minimum_required(VERSION 3.20)

project(teleop_bridge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(zenohc REQUIRED)
find_package(zenohcxx REQUIRED)

add_executable(teleop_bridge
    bridge/src/main.cpp
    bridge/src/transport/tcp_transport.cpp
)

target_link_libraries(teleop_bridge PRIVATE
    zenohcxx::zenohc
)

target_compile_options(teleop_bridge PRIVATE
    -Wall
    -Wextra
    -Wpedantic
)

target_include_directories(teleop_bridge PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/bridge/include
)