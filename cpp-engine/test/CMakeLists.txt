cmake_policy(SET CMP0167 NEW)
find_package(GTest CONFIG REQUIRED)

add_executable(routeflowengine_tests
  test_routing_split.cpp
)

target_link_libraries(routeflowengine_tests
  PRIVATE
  GTest::gtest
  GTest::gtest_main
  routeflow_engine
)

add_test(
  NAME routeflowengine_tests
  COMMAND routeflowengine_tests
)