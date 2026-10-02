# Bazel test

`msbuild_graph_test` selects one project's complete graph-built runtime output.
Bazel caches the test result from that output, declared data/settings/tools, runtime
host and test arguments/environment. A dependency implementation change reruns its
consumer's test even when the consumer DLL does not change.

```starlark
msbuild_graph_test(
    name = "tests",
    graph = ":graph",
    project = "Tests/Tests.csproj",
    framework = "net10.0",  # Needed when the project has multiple variants.
    test_protocol = "executable",
)
```

## Protocols

| Protocol | Launch and result contract |
| --- | --- |
| `executable` | Run a .NET program; exit code determines success |
| `mtp` | Run the MTP executable directly; collect TRX and normalize Bazel XML |
| `vstest` | Launch a declared VSTest console runner and adapters; collect TRX/XML |

MTP programs need no separate runner. VSTest assemblies need an explicit
`msbuild_test_tool` runner plus adapters from locked packages; this avoids ambient
`dotnet test` resolution and gives Bazel complete test inputs. SDK compilation and
framework choice remain MSBuild behavior. VSTest requires a `dotnet` runtime host;
source `corerun` hosts support executable tests.

Use `test_runner`, `test_adapters`, `test_settings` or `test_settings_output`,
`test_working_directory`, `data_paths`, `test_output_dirs`, `env` and ordinary Bazel
`size`/`timeout` as needed. Settings and generated settings are mutually exclusive.
Paths must be safe and relative. `test_diagnostics` is VSTest-only; sharding is not
supported. Runtime environment supplied by the provider cannot replace reserved
host-path variables.

`--test_filter` uses the protocol's filter option; MTP projects can declare
`test_filter_argument`. Empty selections fail unless `allow_empty_tests` is explicit.
Failures, crashes, timeouts and malformed/missing results fail the test. Declared
outputs are preserved under Bazel test outputs; XML records cases and outcomes.

## Validation

`python3 tests/graph_build/protocols.py` creates real MTP and xUnit/VSTest projects
with locked packages. It checks pass/fail/filter/empty/recovery cases, retained
output, unchanged-test caching and dependency implementation invalidation. Add
`--graph-worker` in the qualified Linux environment. The
[upstream runtime suites](runtime-qualification.md) use executable tests with their
reviewed source-built host/harness contracts; their results are separate evidence.
