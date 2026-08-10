cmake_minimum_required(VERSION 3.15)
project(RouteFlowEngine LANGUAGES CXX)

cmake_policy(SET CMP0167 NEW)
if(POLICY CMP0148)
  cmake_policy(SET CMP0148 NEW)
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

option(BUILD_TESTING "Enable tests" ON)

if(MSVC)
  add_compile_options(/W4)
else()
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

set(PYBIND11_FINDPYTHON ON)

find_package(Python3 REQUIRED COMPONENTS Interpreter Development.Module)
find_package(Boost REQUIRED)

execute_process(
  COMMAND "${Python3_EXECUTABLE}" -m pybind11 --cmakedir
  OUTPUT_VARIABLE PYBIND11_CMAKE_DIR
  OUTPUT_STRIP_TRAILING_WHITESPACE
  RESULT_VARIABLE PYBIND11_CMAKE_DIR_RESULT
  ERROR_QUIET
)

if(PYBIND11_CMAKE_DIR_RESULT EQUAL 0 AND EXISTS "${PYBIND11_CMAKE_DIR}")
  message(STATUS "Found pybind11 at: ${PYBIND11_CMAKE_DIR}")
  list(APPEND CMAKE_PREFIX_PATH "${PYBIND11_CMAKE_DIR}")
else()
  message(WARNING "Could not auto-detect pybind11 CMake directory. Install with: ${Python3_EXECUTABLE} -m pip install pybind11")
endif()

find_package(pybind11 CONFIG REQUIRED)

add_library(routeflow_engine STATIC
  src/routing.cpp
  src/orderbook.cpp
  src/json_bootstrap.cpp
  src/uniswap_v2.cpp
)

target_include_directories(routeflow_engine PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${Boost_INCLUDE_DIRS}
)

set_target_properties(routeflow_engine PROPERTIES
  POSITION_INDEPENDENT_CODE ON
)

pybind11_add_module(routeflowengine
  src/pythonbindings.cpp
)

target_include_directories(routeflowengine PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${Boost_INCLUDE_DIRS}
)

target_link_libraries(routeflowengine PRIVATE
  routeflow_engine
)

include(CTest)

if(BUILD_TESTING)
    include(FetchContent)

    FetchContent_Declare(
        googletest
        GIT_REPOSITORY https://github.com/google/googletest.git
        GIT_TAG v1.16.0
    )

    set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)

    add_executable(routeflowengine_tests
        test/test_routing_split.cpp
    )

    target_link_libraries(routeflowengine_tests
        PRIVATE
        GTest::gtest
        GTest::gtest_main
        routeflow_engine
    )

    target_include_directories(routeflowengine_tests
        PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
    )

    include(GoogleTest)
    gtest_discover_tests(routeflowengine_tests)
endif()

message(STATUS "RouteFlowEngine build configured successfully")