# Pipelines runtime qualification

Runtime v10.0.0 (`60629d14374c56f1cb51819049ad1fa529307f8d`), SDK 10.0.400,
Bazel 9.2.0, Linux ARM64. This extends the source-built host with the unchanged
upstream `System.IO.Pipelines.Tests.csproj` at `net10.0`.

## Result

- **577 additional tests pass**, with exact raw/Bazel names and outcomes. The
  eight-suite total is **118,952 passes / 64 skips**. Existing bounded name
  normalization remains unchanged for earlier suites.
- All **96 observed processes** load zero installed runtime components. The
  declared host still contains 121 source-built shared assemblies, one private
  formatter and eight native products.
- The new graph reuses **280/281 managed actions**; only the added test assembly
  compiles. No upstream project, test source, or production rule was changed.
- The authored `SkipUseReferenceAssembly=true` dependency preserves the tests'
  access to Pipelines internals. A body edit recompiles exactly the implementation
  and this test assembly, leaves the public contract unchanged, and reruns all
  eight suites. Source restoration compiles and executes nothing.
- All eight suites reject a deliberately incorrect CoreLib identity.
- With the producer stopped, a relocated independent consumer recovers
  **281/281 managed actions, 5/5 native actions and 121/121 layouts**, plus all
  eight cached test results. All **2,815 output hashes** match. Forced execution
  preserves parity and zero installed runtime loads.

See [recorded evidence](runtime-pipelines-evidence.json). The cold timings in
[runtime cold timing](runtime-cold-timing.md) predate this extra suite.

## Reproduce

Use the existing source checkout and declared native archives from the
[loaded-closure workflow](runtime-loaded-closure.md). Run
`subset_prepare.py SOURCE pipelines OUTPUT --vstest VSTEST_ARCHIVE`, then compose
its host with `subset_host.py` and the five native input directories.

`native_raw_products.py WORKSPACE OUTPUT` independently compiles the native
control from the declared source/toolchain archives. Its orchestration program is
built directly with the pinned SDK; no Bazel-produced native output is reused.
Pass `OUTPUT/products` to `subset_raw.py`, then run `subset_remote.py --seed`.

For `subset_controls.py`, use the Pipelines body mutation from the loaded-closure
workflow, with a fresh mutation value, and add:

```sh
--recompiled-dependent //upstream:src_libraries_System.IO.Pipelines_tests_System.IO.Pipelines.Tests_net10.0
```

This option specifies an exact additional compilation requirement; it does not
relax the check to permit arbitrary rebuilds. Copy only declared inputs, raw
reports and the seed to a separate container, stop the producer, and run
`subset_remote.py --expect SEED`. Require `loaded_inventory.py --require-empty`.

The subsequent [source-only host](runtime-source-host.md) removes the unused
installed template files and uses 10.0.0 framework metadata. This remains a
selected library-test qualification, not full CoreCLR/JIT, other-platform or
remote-execution support.
