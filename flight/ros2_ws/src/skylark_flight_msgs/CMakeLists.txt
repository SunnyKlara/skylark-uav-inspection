cmake_minimum_required(VERSION 3.8)
project(skylark_flight_msgs)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

find_package(action_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  # ---- msg：状态与感知数据 ----
  "msg/VehicleState.msg"
  "msg/FlightHealth.msg"
  "msg/Detection.msg"
  "msg/DetectionArray.msg"
  "msg/GeoTaggedDetection.msg"
  "msg/GeoTaggedDetectionArray.msg"

  # ---- action：飞行动作（长耗时、可取消、有反馈）----
  "action/Takeoff.action"
  "action/Land.action"
  "action/Orbit.action"
  "action/InspectSweep.action"
  "action/Revisit.action"

  # ---- srv：即时指令 ----
  "srv/SetSpeed.srv"
  "srv/SetReposition.srv"
  "srv/AbortMission.srv"

  DEPENDENCIES
    action_msgs
    builtin_interfaces
    geometry_msgs
    std_msgs
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
