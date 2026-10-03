# Installed consumer fixture

This small external project consumes only the installed
`FaultDebugLegacy.cmake` module and `libfaultdebug_runtime.so`. It builds one
C and one C++ executable, each with a normal path and a deliberate null-store
fault path. The v1.0 acceptance runner configures it with an install prefix,
builds it, checks clean termination, and runs the fault paths through the
FaultDebug launcher.
