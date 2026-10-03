# Instrumentation profiles

The CMake helpers and `scripts/faultdebug-cc` accept the same profile through
the CMake cache variable `FAULTDEBUG_INSTRUMENT_PROFILE` or the environment
variable `FAULTDEBUG_INSTRUMENT_PROFILE` for wrapper builds. `legacy` remains
the default so existing builds retain their previous behavior: instrument all
named source files unless an include or exclude filter says otherwise.

| Profile | Source selection |
| --- | --- |
| `legacy` | All named sources by default. The optional include regex narrows the set; the explicit exclude regex removes matches. |
| `minimal` | Instrument only sources matching a non-empty include regex. With no include regex, instrument no source files. The explicit exclude regex still wins. |
| `recommended` | Instrument project target sources by default, excluding path components named `generated` or `vendor`. An include regex narrows the set; the explicit exclude regex still wins. |
| `full` | Instrument every named source, ignoring include filters and the recommended generated/vendor exclusions. The explicit exclude regex still wins. |

The profiles are opt-in choices; no source path is guessed to be
application-owned. In `recommended`, “project sources” means source files
listed on the instrumented target or named directly in compiler arguments.
Path-based generated/vendor exclusions are defaults for that profile and can
be extended with `FAULTDEBUG_INSTRUMENT_EXCLUDE_REGEX`. Full mode intentionally
opts those paths back in unless the user supplies an explicit exclusion.
Invalid profile names fail configuration or wrapper invocation. CMake prints
the profile, configured filters, and each source decision; the wrapper prints
the profile and decision for compile commands that name a source file.

## CMake

Set the profile and optional filters at configure time:

```bash
cmake -S . -B build-selective \
  -DFAULTDEBUG_INSTRUMENT_PROFILE=recommended \
  -DFAULTDEBUG_INSTRUMENT_INCLUDE_REGEX='/(src|app)/' \
  -DFAULTDEBUG_INSTRUMENT_EXCLUDE_REGEX='/generated-special/'
cmake --build build-selective
```

The include regex acts as an allowlist for source paths. The explicit exclude
regex takes precedence when both match. The helper adds `-finstrument-functions`
only to selected source files, so excluded files do not need a compiler-specific
disable flag. `faultdebug_instrument(target)` applies this policy to a target owned by
this project; installed CMake consumers can use
`faultdebug_instrument_existing(target)` from `FaultDebugLegacy.cmake`.
Legacy with no filters keeps the original target-wide flags. Path-filtered
profiles need concrete source paths; CMake reports a configure error for
generator-expression source entries it cannot classify instead of silently
guessing their profile.

## Make and autotools

The wrapper uses the same profile and filter names:

```bash
FAULTDEBUG_REAL_CC=clang \
FAULTDEBUG_REAL_CXX=clang++ \
FAULTDEBUG_LINK_DRIVER=clang++ \
FAULTDEBUG_RUNTIME_DIR="$PWD/build" \
FAULTDEBUG_INSTRUMENT_PROFILE=recommended \
FAULTDEBUG_INSTRUMENT_INCLUDE_REGEX='/(src|app)/' \
FAULTDEBUG_INSTRUMENT_EXCLUDE_REGEX='/generated-special/' \
  make CC="$PWD/scripts/faultdebug-cc" CXX="$PWD/scripts/faultdebug-cxx"
```

The wrapper applies the decision to compile commands that name a source file
and links the runtime on link commands. It does not inspect response-file
contents or infer source paths hidden in build-system-specific arguments. For
object-only links, set `FAULTDEBUG_LINK_DRIVER=clang++` (or the chosen C++
linker) explicitly. `faultdebug-cxx` remains a convenience wrapper for builds
that can use it as both compiler and linker; `faultdebug-cc` cannot infer C++
from an object-only link without the explicit override.

Selective instrumentation changes which runtime events can be observed. Static
index edges and source lookup remain available, but an excluded function must
remain unresolved when no committed runtime event identifies it.
