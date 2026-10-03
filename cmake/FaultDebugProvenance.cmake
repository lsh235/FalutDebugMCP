function(faultdebug_add_provenance target source_manifest)
  if(NOT TARGET ${target})
    message(FATAL_ERROR "faultdebug_add_provenance: unknown target ${target}")
  endif()
  set(_out "${CMAKE_CURRENT_BINARY_DIR}/${target}.faultdebug.manifest.json")
  add_custom_command(TARGET ${target} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E env
      "PYTHONPATH=${CMAKE_SOURCE_DIR}"
      ${Python3_EXECUTABLE} -m faultdebug.provenance manifest
      --output "${_out}"
      --binary "$<TARGET_FILE:${target}>"
      --source-manifest "${source_manifest}"
      --compile-commands "${CMAKE_BINARY_DIR}/compile_commands.json"
    BYPRODUCTS "${_out}"
    VERBATIM)
endfunction()

function(faultdebug_add_auto_provenance target)
  if(NOT TARGET ${target})
    message(FATAL_ERROR "faultdebug_add_auto_provenance: unknown target ${target}")
  endif()
  set(_snapshot_dir "${CMAKE_BINARY_DIR}/faultdebug-source-snapshot")
  set(_source_manifest "${_snapshot_dir}/source-manifest.json")
  add_custom_command(OUTPUT "${_source_manifest}"
    COMMAND ${CMAKE_COMMAND} -E remove_directory "${_snapshot_dir}"
    COMMAND ${CMAKE_COMMAND} -E env "PYTHONPATH=${CMAKE_SOURCE_DIR}" ${Python3_EXECUTABLE} -m faultdebug.provenance snapshot --root "${CMAKE_SOURCE_DIR}" --output "${_snapshot_dir}"
    VERBATIM)
  add_custom_target(${target}_faultdebug_source_snapshot DEPENDS "${_source_manifest}")
  add_dependencies(${target} ${target}_faultdebug_source_snapshot)
  faultdebug_add_provenance(${target} "${_source_manifest}")
endfunction()
