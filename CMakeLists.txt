cmake_minimum_required(VERSION 3.20)
project(faultdebug VERSION 1.2.0 LANGUAGES C CXX)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON CACHE BOOL "Export compilation database" FORCE)
option(FAULTDEBUG_ENABLE_PROVENANCE "Capture source snapshot and manifest during build" ON)
option(FAULTDEBUG_BUILD_TESTS "Build native fixtures" ON)
option(FAULTDEBUG_BUILD_SHOP "Build the container shopping fault fixture boundary" OFF)
set(FAULTDEBUG_PYTHON_EXECUTABLE "" CACHE FILEPATH
  "Python interpreter used for provenance and native validation")
if(FAULTDEBUG_ENABLE_PROVENANCE OR FAULTDEBUG_BUILD_TESTS)
  if(FAULTDEBUG_PYTHON_EXECUTABLE)
    set(Python3_EXECUTABLE "${FAULTDEBUG_PYTHON_EXECUTABLE}" CACHE FILEPATH
      "Python interpreter used by faultdebug" FORCE)
  endif()
  find_package(Python3 COMPONENTS Interpreter REQUIRED)
  message(STATUS "FaultDebug Python interpreter: ${Python3_EXECUTABLE}")
endif()
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/FaultDebugProvenance.cmake)
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/FaultDebugSelective.cmake)

include(GNUInstallDirs)
find_package(Threads REQUIRED)
add_library(faultdebug_runtime SHARED runtime/faultdebug_runtime.c)
target_include_directories(faultdebug_runtime PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>)
set_target_properties(faultdebug_runtime PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS OFF)
set_target_properties(faultdebug_runtime PROPERTIES VERSION ${PROJECT_VERSION} SOVERSION 1)
target_compile_options(faultdebug_runtime PRIVATE -Wall -Wextra -Wpedantic -fno-omit-frame-pointer -fno-lto)
target_link_options(faultdebug_runtime PRIVATE -Wl,--build-id=sha1)
target_link_libraries(faultdebug_runtime PUBLIC Threads::Threads ${CMAKE_DL_LIBS})
if(FAULTDEBUG_ENABLE_PROVENANCE)
  set(FAULTDEBUG_SOURCE_SNAPSHOT_DIR "${CMAKE_BINARY_DIR}/faultdebug-source-snapshot")
  set(FAULTDEBUG_SOURCE_MANIFEST "${FAULTDEBUG_SOURCE_SNAPSHOT_DIR}/source-manifest.json" CACHE FILEPATH "Immutable source manifest captured during build" FORCE)
  add_custom_command(OUTPUT "${FAULTDEBUG_SOURCE_MANIFEST}"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${FAULTDEBUG_SOURCE_SNAPSHOT_DIR}"
    COMMAND ${CMAKE_COMMAND} -E env "PYTHONPATH=${CMAKE_SOURCE_DIR}" ${Python3_EXECUTABLE} -m faultdebug.provenance snapshot --root "${CMAKE_SOURCE_DIR}" --output "${FAULTDEBUG_SOURCE_SNAPSHOT_DIR}"
    VERBATIM)
  add_custom_target(faultdebug_source_snapshot DEPENDS "${FAULTDEBUG_SOURCE_MANIFEST}")
  add_dependencies(faultdebug_runtime faultdebug_source_snapshot)
  faultdebug_add_provenance(faultdebug_runtime "${FAULTDEBUG_SOURCE_MANIFEST}")
else()
  # Clear a stale cache value when a build tree is reconfigured with
  # provenance disabled; integration helpers must not reference a missing
  # source-snapshot target.
  set(FAULTDEBUG_SOURCE_MANIFEST "" CACHE FILEPATH
    "Immutable source manifest captured during build" FORCE)
endif()

function(faultdebug_instrument target)
  if(NOT TARGET ${target})
    message(FATAL_ERROR "faultdebug_instrument: unknown target ${target}")
  endif()
  target_link_libraries(${target} PRIVATE faultdebug_runtime)
  set_property(TARGET ${target} APPEND PROPERTY BUILD_RPATH "$<TARGET_FILE_DIR:faultdebug_runtime>")
  faultdebug_apply_source_filters(${target})
  target_link_options(${target} PRIVATE -Wl,--build-id=sha1)
  if(FAULTDEBUG_SOURCE_MANIFEST)
    add_dependencies(${target} faultdebug_source_snapshot)
    faultdebug_add_provenance(${target} "${FAULTDEBUG_SOURCE_MANIFEST}")
  endif()
endfunction()

if(FAULTDEBUG_BUILD_TESTS AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/test/CMakeLists.txt")
  enable_testing()
  add_subdirectory(test)
endif()

if(FAULTDEBUG_BUILD_SHOP)
  add_subdirectory(test/shop)
endif()

install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(TARGETS faultdebug_runtime
  EXPORT faultdebugTargets
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
  LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
  RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
include(CMakePackageConfigHelpers)
set(FAULTDEBUG_CMAKE_INSTALL_DIR "${CMAKE_INSTALL_LIBDIR}/cmake/faultdebug")
configure_package_config_file(
  "${CMAKE_CURRENT_SOURCE_DIR}/cmake/faultdebugConfig.cmake.in"
  "${CMAKE_CURRENT_BINARY_DIR}/faultdebugConfig.cmake"
  INSTALL_DESTINATION "${FAULTDEBUG_CMAKE_INSTALL_DIR}")
write_basic_package_version_file(
  "${CMAKE_CURRENT_BINARY_DIR}/faultdebugConfigVersion.cmake"
  VERSION ${PROJECT_VERSION}
  COMPATIBILITY SameMajorVersion)
install(EXPORT faultdebugTargets
  FILE faultdebugTargets.cmake
  NAMESPACE faultdebug::
  DESTINATION "${FAULTDEBUG_CMAKE_INSTALL_DIR}")
install(FILES
  "${CMAKE_CURRENT_BINARY_DIR}/faultdebugConfig.cmake"
  "${CMAKE_CURRENT_BINARY_DIR}/faultdebugConfigVersion.cmake"
  cmake/FaultDebugLegacy.cmake cmake/FaultDebugProvenance.cmake
  cmake/FaultDebugSelective.cmake
  DESTINATION "${FAULTDEBUG_CMAKE_INSTALL_DIR}")
configure_file(cmake/faultdebug.pc.in "${CMAKE_CURRENT_BINARY_DIR}/faultdebug.pc" @ONLY)
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/faultdebug.pc"
  DESTINATION "${CMAKE_INSTALL_LIBDIR}/pkgconfig")
install(FILES cmake/FaultDebugLegacy.cmake cmake/FaultDebugProvenance.cmake
  cmake/FaultDebugSelective.cmake
  DESTINATION ${CMAKE_INSTALL_DATADIR}/faultdebug/cmake)
