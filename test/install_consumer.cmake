if(NOT DEFINED FAULTDEBUG_BUILD_DIR OR NOT DEFINED FAULTDEBUG_SOURCE_DIR OR
   NOT DEFINED FAULTDEBUG_CONSUMER_SOURCE_DIR)
  message(FATAL_ERROR "install consumer test requires build/source paths")
endif()
set(_root "${FAULTDEBUG_BUILD_DIR}/install-consumer")
set(_prefix "${_root}/prefix")
set(_build "${_root}/build")
file(REMOVE_RECURSE "${_root}")
file(MAKE_DIRECTORY "${_root}")
execute_process(
  COMMAND "${CMAKE_COMMAND}" --install "${FAULTDEBUG_BUILD_DIR}" --prefix "${_prefix}"
  RESULT_VARIABLE _install_result OUTPUT_VARIABLE _install_out ERROR_VARIABLE _install_err)
if(NOT _install_result EQUAL 0)
  message(FATAL_ERROR "faultdebug install failed: ${_install_err}")
endif()
execute_process(
  COMMAND "${CMAKE_COMMAND}" -S "${FAULTDEBUG_CONSUMER_SOURCE_DIR}" -B "${_build}"
          -DCMAKE_PREFIX_PATH=${_prefix} -DCMAKE_BUILD_TYPE=Release
  RESULT_VARIABLE _configure_result OUTPUT_VARIABLE _configure_out ERROR_VARIABLE _configure_err)
if(NOT _configure_result EQUAL 0)
  message(FATAL_ERROR "installed consumer configure failed: ${_configure_err}")
endif()
execute_process(
  COMMAND "${CMAKE_COMMAND}" --build "${_build}" --parallel 2
  RESULT_VARIABLE _build_result OUTPUT_VARIABLE _build_out ERROR_VARIABLE _build_err)
if(NOT _build_result EQUAL 0)
  message(FATAL_ERROR "installed consumer build failed: ${_build_err}")
endif()
if(UNIX)
  set(_library_path "${_prefix}/lib")
  execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env "LD_LIBRARY_PATH=${_library_path}" "${_build}/faultdebug_installed_consumer"
    RESULT_VARIABLE _run_result OUTPUT_VARIABLE _run_out ERROR_VARIABLE _run_err)
else()
  execute_process(
    COMMAND "${_build}/faultdebug_installed_consumer"
    RESULT_VARIABLE _run_result OUTPUT_VARIABLE _run_out ERROR_VARIABLE _run_err)
endif()
if(NOT _run_result EQUAL 0)
  message(FATAL_ERROR "installed consumer run failed: ${_run_err}")
endif()
message(STATUS "faultdebug installed consumer: configure/build/run PASS")
