# Source selection helpers for function instrumentation.
include_guard(GLOBAL)

set(FAULTDEBUG_INSTRUMENT_PROFILE "legacy" CACHE STRING
  "Instrumentation profile: legacy, minimal, recommended, or full")
set_property(CACHE FAULTDEBUG_INSTRUMENT_PROFILE PROPERTY STRINGS
  legacy minimal recommended full)
set(FAULTDEBUG_INSTRUMENT_INCLUDE_REGEX "" CACHE STRING
  "Regex allowlist of source paths to instrument")
set(FAULTDEBUG_INSTRUMENT_EXCLUDE_REGEX "" CACHE STRING
  "Regex of source paths to exclude; takes precedence over the profile")

if(NOT FAULTDEBUG_INSTRUMENT_PROFILE MATCHES "^(legacy|minimal|recommended|full)$")
  message(FATAL_ERROR
    "Invalid FAULTDEBUG_INSTRUMENT_PROFILE='${FAULTDEBUG_INSTRUMENT_PROFILE}'; expected legacy, minimal, recommended, or full")
endif()

message(STATUS "FaultDebug instrumentation profile: ${FAULTDEBUG_INSTRUMENT_PROFILE}")
if(FAULTDEBUG_INSTRUMENT_INCLUDE_REGEX)
  message(STATUS "FaultDebug source include filter: ${FAULTDEBUG_INSTRUMENT_INCLUDE_REGEX}")
endif()
if(FAULTDEBUG_INSTRUMENT_EXCLUDE_REGEX)
  message(STATUS "FaultDebug source exclude filter: ${FAULTDEBUG_INSTRUMENT_EXCLUDE_REGEX}")
endif()

function(faultdebug_apply_source_filters target)
  if(NOT TARGET ${target})
    message(FATAL_ERROR "faultdebug_apply_source_filters: unknown target ${target}")
  endif()
  set(_instrument_options
    -finstrument-functions -O0 -g -fno-optimize-sibling-calls -fno-lto
    -fno-omit-frame-pointer)
  set(_target_wide FALSE)
  if((FAULTDEBUG_INSTRUMENT_PROFILE STREQUAL "legacy" AND
      NOT FAULTDEBUG_INSTRUMENT_INCLUDE_REGEX AND
      NOT FAULTDEBUG_INSTRUMENT_EXCLUDE_REGEX) OR
     (FAULTDEBUG_INSTRUMENT_PROFILE STREQUAL "full" AND
      NOT FAULTDEBUG_INSTRUMENT_EXCLUDE_REGEX))
    # Preserve legacy's original target-wide behavior when every source is in.
    # Full mode can use it too when no explicit per-path exclusion is present.
    target_compile_options(${target} PRIVATE ${_instrument_options})
    set(_target_wide TRUE)
  endif()
  get_target_property(_sources ${target} SOURCES)
  if(NOT _sources OR _sources STREQUAL "_sources-NOTFOUND")
    return()
  endif()
  foreach(_source IN LISTS _sources)
    if(_source MATCHES "^\\$<")
      if(_target_wide)
        message(STATUS "FaultDebug: profile=${FAULTDEBUG_INSTRUMENT_PROFILE} source=${_source} decision=instrumented (target-wide)")
        continue()
      endif()
      message(FATAL_ERROR
        "FaultDebug profile '${FAULTDEBUG_INSTRUMENT_PROFILE}' cannot select generator-expression source '${_source}'; list profile-filtered sources explicitly")
    endif()
    set(_path "${_source}")
    if(NOT IS_ABSOLUTE "${_path}")
      get_target_property(_source_dir ${target} SOURCE_DIR)
      set(_path "${_source_dir}/${_path}")
    endif()
    set(_exclude FALSE)
    if(FAULTDEBUG_INSTRUMENT_PROFILE STREQUAL "minimal" AND
       (NOT FAULTDEBUG_INSTRUMENT_INCLUDE_REGEX OR
        NOT "${_path}" MATCHES "${FAULTDEBUG_INSTRUMENT_INCLUDE_REGEX}"))
      set(_exclude TRUE)
    endif()
    if(NOT FAULTDEBUG_INSTRUMENT_PROFILE STREQUAL "full" AND
       NOT FAULTDEBUG_INSTRUMENT_PROFILE STREQUAL "minimal" AND
       FAULTDEBUG_INSTRUMENT_INCLUDE_REGEX AND
       NOT "${_path}" MATCHES "${FAULTDEBUG_INSTRUMENT_INCLUDE_REGEX}")
      set(_exclude TRUE)
    endif()
    if(FAULTDEBUG_INSTRUMENT_PROFILE STREQUAL "recommended" AND
       "${_path}" MATCHES "(^|/)(generated|vendor)/")
      set(_exclude TRUE)
    endif()
    if(FAULTDEBUG_INSTRUMENT_EXCLUDE_REGEX AND
       "${_path}" MATCHES "${FAULTDEBUG_INSTRUMENT_EXCLUDE_REGEX}")
      set(_exclude TRUE)
    endif()
    if(_exclude)
      message(STATUS "FaultDebug: profile=${FAULTDEBUG_INSTRUMENT_PROFILE} source=${_path} decision=excluded")
    elseif(NOT _target_wide)
      get_source_file_property(_existing_options "${_path}" COMPILE_OPTIONS)
      if(NOT _existing_options OR _existing_options MATCHES "NOTFOUND$")
        set(_existing_options "")
      endif()
      set_source_files_properties("${_path}" PROPERTIES
        COMPILE_OPTIONS "${_existing_options};${_instrument_options}")
      message(STATUS "FaultDebug: profile=${FAULTDEBUG_INSTRUMENT_PROFILE} source=${_path} decision=instrumented")
    else()
      message(STATUS "FaultDebug: profile=${FAULTDEBUG_INSTRUMENT_PROFILE} source=${_path} decision=instrumented (target-wide)")
    endif()
  endforeach()
endfunction()
