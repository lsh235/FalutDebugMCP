cmake_minimum_required(VERSION 3.20)
project(faultdebug_fixtures LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_C_EXTENSIONS OFF)
set(CMAKE_CXX_EXTENSIONS OFF)
add_compile_options(-O0 -g -fno-lto -fno-optimize-sibling-calls -fno-omit-frame-pointer)

add_executable(fd_c_chain programs/c_chain/main.c programs/c_chain/chain_a.c
  programs/c_chain/chain_b.c programs/c_chain/chain_c.c programs/c_chain/chain_d.c)
add_executable(fd_cpp_chain programs/cpp_chain/main.cpp programs/cpp_chain/chain_a.cpp
  programs/cpp_chain/chain_b.cpp programs/cpp_chain/chain_c.cpp)
add_executable(fd_recursion programs/recursion/main.c)
add_executable(fd_signals programs/signals/main.c)
add_executable(fd_threads programs/multithread/main.c)
add_executable(fd_wrap programs/wrap/main.c)
add_executable(fd_slot_reuse programs/thread_slot_reuse/main.c)
add_library(fd_startup_module SHARED programs/pie_dso/startup_module.c)
add_executable(fd_pie_dso programs/pie_dso/main.c)
add_executable(fd_soak programs/soak/main.c)
add_executable(fd_branch programs/branch/main.c)
add_executable(fd_exceptions programs/exceptions/main.cpp)
add_executable(fd_stack_exhaust programs/stack_exhaust/main.c)
add_executable(fd_simultaneous programs/simultaneous/main.c)
add_library(fd_complex_shared SHARED programs/complex/shared.cpp)
add_executable(fd_complex programs/complex/main.cpp programs/complex/helper.cpp)
add_executable(fd_process_timeline programs/process_timeline/main.c)
add_executable(fd_rpc_emit_fault programs/rpc_emit_fault/main.c)
add_executable(fd_snapshot_stress programs/snapshot_stress/main.c)
target_include_directories(fd_snapshot_stress PRIVATE "${CMAKE_SOURCE_DIR}/include")
target_link_libraries(fd_snapshot_stress PRIVATE pthread)
add_executable(fd_rpc_scope_probe programs/rpc_scope/main.cc)
add_executable(fd_abi_probe programs/abi_probe/main.c)
target_include_directories(fd_abi_probe PRIVATE "${CMAKE_SOURCE_DIR}/include")
if(UNIX AND NOT APPLE)
  set(FAULTDEBUG_VALIDATION_PYTHON "${Python3_EXECUTABLE}")
  if(FAULTDEBUG_PYTHON_EXECUTABLE)
    set(FAULTDEBUG_VALIDATION_PYTHON "${FAULTDEBUG_PYTHON_EXECUTABLE}")
  endif()
  add_executable(fd_rpc_sidecar_probe programs/rpc_sidecar/main.c)
  target_include_directories(fd_rpc_sidecar_probe PRIVATE
    "${CMAKE_SOURCE_DIR}/include")
  target_link_libraries(fd_rpc_sidecar_probe PRIVATE ${CMAKE_DL_LIBS})
  add_test(NAME fd_rpc_sidecar_probe
    COMMAND fd_rpc_sidecar_probe $<TARGET_FILE:faultdebug_runtime>)
  add_test(NAME fd_rpc_scope_probe COMMAND fd_rpc_scope_probe)
  add_test(NAME fd_abi_probe COMMAND fd_abi_probe)
  add_test(NAME fd_python_abi_decoder
    COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/abi_decoder_contract.py")
  add_test(NAME fd_python_decoder_capacity
    COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/decoder_capacity.py"
      $<TARGET_FILE:fd_threads>)
  add_test(NAME fd_python_doctor_benchmark
    COMMAND ${FAULTDEBUG_VALIDATION_PYTHON} "${CMAKE_CURRENT_SOURCE_DIR}/doctor_benchmark.py"
      --build-dir "${CMAKE_BINARY_DIR}" --require-runtime-smoke)
  set_tests_properties(fd_python_doctor_benchmark PROPERTIES
    ENVIRONMENT "FAULTDEBUG_RUNTIME_DIR=${CMAKE_BINARY_DIR}")
  add_test(NAME fd_python_negative_cases
    COMMAND ${FAULTDEBUG_VALIDATION_PYTHON} "${CMAKE_CURRENT_SOURCE_DIR}/negative_cases_contract.py")
  add_test(NAME fd_python_validation_status
    COMMAND ${FAULTDEBUG_VALIDATION_PYTHON} "${CMAKE_CURRENT_SOURCE_DIR}/validation_status_contract.py")
  add_test(NAME fd_python_grpc_runner_logs
    COMMAND ${FAULTDEBUG_VALIDATION_PYTHON} "${CMAKE_CURRENT_SOURCE_DIR}/grpc_runner_contract.py")
  add_test(NAME fd_python_collector_agent_bounded
    COMMAND ${FAULTDEBUG_VALIDATION_PYTHON} "${CMAKE_CURRENT_SOURCE_DIR}/collector_agent_bounded.py")
  add_test(NAME fd_python_snapshot_consistency
    COMMAND ${FAULTDEBUG_VALIDATION_PYTHON} "${CMAKE_CURRENT_SOURCE_DIR}/snapshot_consistency_contract.py")
  add_test(NAME fd_python_snapshot_stress
    COMMAND ${FAULTDEBUG_VALIDATION_PYTHON} "${CMAKE_CURRENT_SOURCE_DIR}/snapshot_stress.py"
      --binary $<TARGET_FILE:fd_snapshot_stress>
      --output "${CMAKE_CURRENT_BINARY_DIR}/snapshot-stress.json")
  add_test(NAME fd_python_libuv_repeatability
    COMMAND ${FAULTDEBUG_VALIDATION_PYTHON}
      "${CMAKE_CURRENT_SOURCE_DIR}/external/test_libuv_repeatability.py")
  add_test(NAME fd_python_v12_release_gate_contract
    COMMAND ${FAULTDEBUG_VALIDATION_PYTHON}
      "${CMAKE_CURRENT_SOURCE_DIR}/v12_release_gate_contract.py")
  add_test(NAME fd_python_soak_telemetry_contract
    COMMAND ${FAULTDEBUG_VALIDATION_PYTHON}
      "${CMAKE_CURRENT_SOURCE_DIR}/soak_telemetry_contract.py")
  add_test(NAME fd_install_consumer
    COMMAND ${CMAKE_COMMAND}
      -DFAULTDEBUG_BUILD_DIR=${CMAKE_BINARY_DIR}
      -DFAULTDEBUG_SOURCE_DIR=${CMAKE_SOURCE_DIR}
      -DFAULTDEBUG_CONSUMER_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/install_consumer
      -P ${CMAKE_CURRENT_SOURCE_DIR}/install_consumer.cmake)
endif()
target_link_libraries(fd_complex PRIVATE fd_complex_shared pthread)
target_compile_options(fd_complex_shared PRIVATE -fPIC -finstrument-functions)
target_link_options(fd_complex_shared PRIVATE -Wl,--build-id=sha1)
target_link_libraries(fd_simultaneous PRIVATE pthread)
target_link_libraries(fd_soak PRIVATE pthread)
target_link_libraries(fd_exceptions PRIVATE stdc++)
target_link_libraries(fd_pie_dso PRIVATE fd_startup_module)
target_compile_options(fd_startup_module PRIVATE -fPIC -finstrument-functions)
target_link_options(fd_startup_module PRIVATE -Wl,--build-id=sha1)
if(FAULTDEBUG_SOURCE_MANIFEST)
  add_dependencies(fd_startup_module faultdebug_source_snapshot)
  faultdebug_add_provenance(fd_startup_module "${FAULTDEBUG_SOURCE_MANIFEST}")
endif()

foreach(t fd_c_chain fd_cpp_chain fd_recursion fd_signals fd_threads fd_wrap fd_slot_reuse fd_pie_dso fd_soak fd_branch fd_exceptions fd_stack_exhaust fd_simultaneous fd_complex fd_process_timeline fd_rpc_emit_fault fd_snapshot_stress fd_rpc_scope_probe)
  faultdebug_instrument(${t})
  target_link_options(${t} PRIVATE -pie)
endforeach()
faultdebug_instrument(fd_complex_shared)

if(UNIX AND NOT APPLE)
  add_test(NAME fd_spool_test
    COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/spool_test.py")
  add_test(NAME fd_rpc_sidecar_e2e
    COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/rpc_sidecar_e2e.py"
      --binary $<TARGET_FILE:fd_rpc_emit_fault>
      --output "${CMAKE_CURRENT_BINARY_DIR}/rpc-sidecar-e2e")
  add_test(NAME fd_session_collector
    COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/session_collector_test.py"
      --binary $<TARGET_FILE:fd_signals>)
  add_test(NAME fd_resident_agent
    COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/agent_test.py"
      --peer-binary $<TARGET_FILE:fd_soak>
      --trigger-binary $<TARGET_FILE:fd_signals>)
endif()

# The executable exports the one recorder instance for the instrumented startup
# DSO; the DSO itself must not link a private copy of the runtime.
target_link_options(fd_pie_dso PRIVATE -rdynamic)

if (CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|AMD64")
  target_compile_definitions(fd_signals PRIVATE FD_X86_64=1)
endif()

# Optional asynchronous gRPC proxy fixture.  The core fixture suite must stay
# buildable on hosts without gRPC, so missing packages/tools are reported and
# skipped instead of turning the ordinary test configure into a failure.
option(FAULTDEBUG_BUILD_GRPC_PROXY
  "Build the optional asynchronous gRPC proxy fixture" ON)
if(FAULTDEBUG_BUILD_GRPC_PROXY)
  find_package(Protobuf QUIET CONFIG)
  find_package(gRPC QUIET CONFIG)
  find_program(FAULTDEBUG_PROTOC protoc)
  if(TARGET gRPC::grpc++ AND TARGET protobuf::libprotobuf AND
     TARGET protobuf::protoc AND TARGET gRPC::grpc_cpp_plugin AND
     FAULTDEBUG_PROTOC)
    set(FAULTDEBUG_GRPC_PROXY_DIR
        "${CMAKE_CURRENT_SOURCE_DIR}/programs/grpc_proxy")
    set(FAULTDEBUG_GRPC_PROXY_GEN_DIR
        "${CMAKE_CURRENT_BINARY_DIR}/grpc_proxy_generated")
    set(FAULTDEBUG_GRPC_PROXY_PROTO
        "${FAULTDEBUG_GRPC_PROXY_DIR}/echo.proto")
    set(FAULTDEBUG_GRPC_PROXY_GEN_SRCS
        "${FAULTDEBUG_GRPC_PROXY_GEN_DIR}/echo.pb.cc"
        "${FAULTDEBUG_GRPC_PROXY_GEN_DIR}/echo.grpc.pb.cc")
    set(FAULTDEBUG_GRPC_PROXY_GEN_HDRS
        "${FAULTDEBUG_GRPC_PROXY_GEN_DIR}/echo.pb.h"
        "${FAULTDEBUG_GRPC_PROXY_GEN_DIR}/echo.grpc.pb.h")
    add_custom_command(
      OUTPUT ${FAULTDEBUG_GRPC_PROXY_GEN_SRCS} ${FAULTDEBUG_GRPC_PROXY_GEN_HDRS}
      COMMAND ${CMAKE_COMMAND} -E make_directory
              ${FAULTDEBUG_GRPC_PROXY_GEN_DIR}
      COMMAND $<TARGET_FILE:protobuf::protoc>
              --proto_path=${FAULTDEBUG_GRPC_PROXY_DIR}
              --cpp_out=${FAULTDEBUG_GRPC_PROXY_GEN_DIR}
              --grpc_out=${FAULTDEBUG_GRPC_PROXY_GEN_DIR}
              --plugin=protoc-gen-grpc=$<TARGET_FILE:gRPC::grpc_cpp_plugin>
              "${FAULTDEBUG_GRPC_PROXY_PROTO}"
      DEPENDS "${FAULTDEBUG_GRPC_PROXY_PROTO}"
      VERBATIM)
    add_executable(fd_grpc_async_proxy
      programs/grpc_proxy/main.cc
      programs/grpc_proxy/trace.cc
      ${FAULTDEBUG_GRPC_PROXY_GEN_SRCS})
    target_include_directories(fd_grpc_async_proxy PRIVATE
      "${FAULTDEBUG_GRPC_PROXY_GEN_DIR}")
    # Ubuntu's Clang 18 emits a reference to an inline libstdc++ helper when
    # -finstrument-functions is combined with the default GCC 13 headers.
    # Disable that header assertion path for this instrumented fixture; the
    # production target remains free to use its own compiler policy.
    target_compile_definitions(fd_grpc_async_proxy PRIVATE
      _GLIBCXX_ASSERTIONS=0)
    if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
      # gRPC's installed archives are GCC-built; Clang's default constrained
      # template mangling is incompatible with their Abseil inline symbols.
      target_compile_options(fd_grpc_async_proxy PRIVATE
        -fclang-abi-compat=17)
    endif()
    target_link_libraries(fd_grpc_async_proxy PRIVATE
      gRPC::grpc++ protobuf::libprotobuf stdc++ pthread)
    # Instrument only the application-owned trace boundaries.  Applying
    # -finstrument-functions to gRPC headers/generated glue makes one unary
    # RPC consume the bounded ring in dependency frames and obscures the
    # proxy callback.  This is the same selective policy recommended for an
    # existing service: link the runtime to the process and opt in at the
    # service boundary.
    target_link_libraries(fd_grpc_async_proxy PRIVATE faultdebug_runtime)
    set_property(TARGET fd_grpc_async_proxy APPEND PROPERTY BUILD_RPATH
      "$<TARGET_FILE_DIR:faultdebug_runtime>")
    target_compile_options(fd_grpc_async_proxy PRIVATE -O0 -g -fno-lto
      -fno-optimize-sibling-calls -fno-omit-frame-pointer)
    # Keep the gRPC state-machine translation unit out of blanket function
    # instrumentation.  Its template instantiations include dependency code;
    # the explicit application-owned boundaries below provide stable evidence
    # without consuming the bounded ring on gRPC internals.
    set_source_files_properties(programs/grpc_proxy/trace.cc PROPERTIES
      COMPILE_OPTIONS "-finstrument-functions")
    target_link_options(fd_grpc_async_proxy PRIVATE -Wl,--build-id=sha1)
    if(FAULTDEBUG_SOURCE_MANIFEST)
      add_dependencies(fd_grpc_async_proxy faultdebug_source_snapshot)
      faultdebug_add_provenance(fd_grpc_async_proxy
        "${FAULTDEBUG_SOURCE_MANIFEST}")
    endif()
    target_link_options(fd_grpc_async_proxy PRIVATE -pie)
    add_custom_target(fd_grpc_async_proxy_generated DEPENDS
      ${FAULTDEBUG_GRPC_PROXY_GEN_SRCS} ${FAULTDEBUG_GRPC_PROXY_GEN_HDRS})
    add_dependencies(fd_grpc_async_proxy fd_grpc_async_proxy_generated)
    add_test(NAME fd_grpc_v09_scenarios
      COMMAND ${Python3_EXECUTABLE}
              "${CMAKE_CURRENT_SOURCE_DIR}/grpc_v09_scenarios.py"
              --output "${CMAKE_CURRENT_BINARY_DIR}/grpc-v09-scenarios"
              --binary $<TARGET_FILE:fd_grpc_async_proxy>)
    message(STATUS "FaultDebug gRPC proxy fixture: ENABLED")
  else()
    message(STATUS
      "FaultDebug gRPC proxy fixture: SKIPPED (requires gRPC::grpc++, "
      "protobuf::libprotobuf, protoc, and grpc_cpp_plugin)")
  endif()
endif()
