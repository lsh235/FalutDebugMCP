# faultdebug v0.1.0 validation report

Validation was run from the repository root with Ubuntu x86_64 and the
provisioned Clang 18.1.3 toolchain:

```text
.tools/clang/usr/bin/clang-18 --version
Ubuntu clang version 18.1.3 (1ubuntu1)
```

The runner configures the top-level CMake project with `FAULTDEBUG_BUILD_TESTS=ON`,
builds fixtures under `build/test/`, and invokes the real launcher through
`.venv/bin/faultdebug` or `python -m faultdebug.cli`.

## Smoke

Command:

```sh
python3 test/run_tests.py --suite smoke --output /tmp/fd-complex-smoke3
```

Result:

```text
PASS 6   FAIL 0   NOT RUN 0
```

The smoke set includes normal C and C++ chains, a clean normal-return run,
completed-chain-then-fault, and the complex cross-translation-unit/shared
library/IPC/8-thread/fork fixture. The independent complex marker oracle passed.

## Acceptance

Command:

```sh
python3 test/run_tests.py --suite acceptance --output /tmp/fd-acceptance-final
```

Result:

```text
PASS 516   FAIL 0   NOT RUN 0
```

This includes 100 repetitions for each of SIGSEGV, SIGBUS, SIGILL, SIGFPE, and
SIGABRT, plus recursion, multithreading, ring wrap, thread-slot reuse, startup
linked DSO, branch selection, C++ exceptions, simultaneous-fault first-crash
handling, stack exhaustion, and the complex fixture. The simultaneous-fault
case requires valid first-crash metadata; nested-fault observation is recorded
when present but first-crash-wins termination is valid when the second handler
does not re-enter before termination.

## Artifact negative checks

Command:

```sh
python3 test/negative_cases.py /tmp/fd-soak-live.IBDM5P/artifacts
```

Result:

```text
PASS: bad_signal, bad_pc, bad_generation, truncated
unexpected_pass: []
```

These checks operate on the canonical `.fault` artifact format and verify that
invalid crash metadata, generation data, and truncation do not pass the
independent oracle.

## Soak

The soak used one long-lived instrumented process, rather than repeated short
processes:

```text
PID: 389498
Root: /tmp/fd-soak-live.IBDM5P
Log: /tmp/fd-soak-live.IBDM5P/launcher.log
Artifact: /tmp/fd-soak-live.IBDM5P/artifacts/fault-389547.fault
Elapsed: 1800 seconds
Target signal: 11
Collector status: 7, ok=true
RSS samples: 18,732 KB from 1440s through completion
Independent oracle: PASS
```

The source and binary hashes captured at soak start were:

```text
runtime source: a4e5efc1ed001797b6ea1af2404d82f53dd8af41
fixture binary: e4f0422c37f25218faad9b5b777aed2a770c03a9c3ae252db8a5b6b4a051c637
```

## Status interpretation

`PASS` means the stated assertion and its independent evidence passed.
`FAIL` means an assertion failed. `NOT RUN` is retained for unavailable
launcher/oracle dependencies and is never converted into PASS. Normal clean
exit intentionally produces no fault artifact; fault artifacts are expected for
crash and partial-publication cases.
