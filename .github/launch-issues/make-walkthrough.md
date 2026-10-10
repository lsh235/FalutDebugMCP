# Add a minimal GNU Make + compiledb walkthrough

Provide a copyable one-file C/C++ Make example in docs with compiledb output, FaultDebug indexing and opt-in compiler-wrapper instrumentation.

Use test/build_systems/test_compiledb_integration.py as the existing executable reference.

Acceptance:
- Show prerequisites and exact commands for the supported Clang/Python profile.
- Verify that both translation units appear in compile_commands.json.
- Run the example and inspect actual instrumentation symbols.
- Link the example from docs/build-integration-v1.1.md.

Do not add compiledb as a required runtime dependency or claim untested build-system support.
