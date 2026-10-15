
cmake_minimum_required(VERSION 3.20)

project(teleop_bridge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(zenohc REQUIRED)
find_package(zenohcxx REQUIRED)

add_executable(teleop_bridge
    bridge/src/main.cpp
    bridge/src/transport/tcp_transport.cpp
    bridge/src/transport/udp_transport.cpp
    bridge/src/transport/hybrid_transport.cpp
    bridge/src/transport/transport_factory.cpp
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

# --------------------------------------------------
# Unit tests
# --------------------------------------------------

include(CTest)

if(BUILD_TESTING)
    foreach(test_name IN ITEMS
        test_message
        test_rate_limiter
        test_receive_stats
        test_scheduler
    )
        add_executable(${test_name}
            tests/${test_name}.cpp
        )

        target_include_directories(${test_name} PRIVATE
            ${CMAKE_CURRENT_SOURCE_DIR}/bridge/include
        )

        target_compile_options(${test_name} PRIVATE
            -Wall
            -Wextra
            -Wpedantic
        )

        add_test(
            NAME ${test_name}
            COMMAND ${test_name}
        )
    endforeach()

    # UDP transport unit test
    add_executable(test_udp_transport
        tests/test_udp_transport.cpp
        bridge/src/transport/udp_transport.cpp
    )

    target_include_directories(test_udp_transport PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/bridge/include
    )

    target_compile_options(test_udp_transport PRIVATE
        -Wall
        -Wextra
        -Wpedantic
    )

    add_test(
        NAME test_udp_transport
        COMMAND test_udp_transport
    )

    set_tests_properties(test_udp_transport PROPERTIES
        TIMEOUT 5
    )

    # Hybrid transport unit test
    add_executable(test_hybrid_transport
        tests/test_hybrid_transport.cpp
        bridge/src/transport/hybrid_transport.cpp
    )

    target_include_directories(test_hybrid_transport PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/bridge/include
    )

    target_compile_options(test_hybrid_transport PRIVATE
        -Wall
        -Wextra
        -Wpedantic
    )

    add_test(
        NAME test_hybrid_transport
        COMMAND test_hybrid_transport
    )

    set_tests_properties(test_hybrid_transport PROPERTIES
        TIMEOUT 5
    )

endif()
