# API

Follow the [quickstart](../examples/quickstart/README.md) for setup. Load build rules
from `@rules_msbuild//msbuild:defs.bzl`; load `msbuild_sync` from `@rules_msbuild//msbuild:sync.bzl`.
See [design](design.md) for ownership, graph execution and cache invalidation.

## Sync

Declare `msbuild_sync(name = "sync", projects = ["App/App.csproj"])` in the root
BUILD file. Run `bazel run //:sync` and commit `graph.generated.json` and
`graph.generated.bzl`. The generated `app_graph` macro declares the build.

Body edits need no sync. Rerun sync after project/import, source-list, package or
configuration changes. `bazel run //:sync -- --check` rejects stale declarations.

| Sync attribute | Use |
| --- | --- |
| `configuration`, `framework` | Select configuration (default Release) and optional entry framework |
| `inputs` | Map single-file producer labels to workspace-relative paths |
| `package_lock` | Supply a closed package inventory, including package SDKs |
| `package_build`, `package_inputs` | Evaluate package targets/content after offline Restore; declare extra task reads |
| `bindings` | Bind complete tool layouts to MSBuild properties |
| `mappings` | Supply reviewed JSON input/output/dependency contracts |

Mappings use `projectDefaults`, project-path `projects`, `frameworkOverrides`, and
root `entryProperties`. Supported contracts are `documents` (digest, target/task
names, extra inputs), `inputItems`, `evaluationItems`, `outputFiles`,
`inputDirectories`, `temporaryDirectories`, `referenceBoundary`,
`implementationDependencies`, `compilerReference`, `compilerReferences`,
`preparedRestore`, `restoreInputs`, and `restoreOutputs`.
`projectDefaults.properties` sets graph-wide properties. Unknown/duplicate fields
and unsafe paths fail; document changes require renewed contract review.

## Build and artifacts

| Rule | Use |
| --- | --- |
| `msbuild_graph_runner` / `msbuild_graph` | Bootstrap the runner; Build, Pack or Publish an explicit graph contract |
| `msbuild_graph_binary` / `msbuild_graph_test` | Run or test a graph's `project`, selecting `framework` if ambiguous |
| `msbuild_graph_layout` / `msbuild_graph_output` | Export a complete project output layout or a contract-owned file |
| `msbuild_graph_restore` | Prepare offline Restore separately for a matching stable-path graph |
| `msbuild_tool` / `msbuild_file_binding` | Bind a layout entry point to a task property; `msbuild_native_tool` uses the same contract |
| `msbuild_layout` / `msbuild_runtime` | Compose artifacts; describe a complete execution host |
| `msbuild_nuget_package` / `msbuild_generated_nuget_package` | Validate and extract acquired/generated archives |
| `msbuild_nuget_dependencies` / `msbuild_package_lock` | Declare the closed package inventory |
| `msbuild_test_tool` / `msbuild_native_toolchain*` | Select package test tools or acquire native tools |

A handwritten graph supplies `contract`, `srcs`, and optional `input_paths`,
`bindings`, `packages`/`package_lock`. `source_root` removes a Bazel package prefix.
The JSON identifies projects by path and global properties, with explicit inputs
and owned output directories/files. Runtime selectors in `project_outputs` or
`publish_outputs` map `project|framework` to `[directory, assembly_filename, output_type]`.
See [rule attributes](../msbuild/graph.bzl) and [contract fixtures](../tests/graph_build).

NuGet inventories require exact versions, transitive dependencies and acquired
archive/content hashes. Restore is offline; no ambient feed or user cache fills
missing inputs. `allow_multiple_versions = True` permits distinct configured versions.
For SDK Pack, declare its output directory, retain authored Pack behavior, export
the `.nupkg` with `msbuild_graph_output`, and pass it to `msbuild_generated_nuget_package`.

Task/analyzer layouts must include dependencies and data (for managed task libraries,
consider `CopyLocalLockFileAssemblies`). For example:

```starlark
msbuild_graph_layout(name = "tasks_layout", graph = ":tasks_graph", project = "Tasks/Tasks.csproj")
msbuild_tool(name = "task", layout = ":tasks_layout", entry_point = "Tasks.dll")
msbuild_file_binding(name = "binding", tool = ":task", property_name = "TaskLocation")
```

Pass the binding to sync and the generated graph. Content edits invalidate consumers
without resync; property/entry-point changes require sync.

The SDK extension accepts a pinned version or tracked `global.json`.
Declared source-produced SDKs use [`msbuild_sdk`](../msbuild/sdk.bzl); register
`<name>_registered` and `<name>_runtime_registered`. The SDK must be a complete
layout rooted beside `dotnet`; its producer needs a separate bootstrap toolchain.
`runtime_host` selects a declared `msbuild_runtime` (`dotnet` or `corerun`) for
apps/tests independently of compilation. Later hosts run older targets only when
the authored runtimeconfig allows it. Host-path SDK repositories are unsupported.

## Tests

`test_protocol` is `executable` (default, exit status), `mtp` (direct executable),
or `vstest` (declared `test_runner`/`test_adapters` from locked packages).
MTP needs no runner; VSTest requires a dotnet host. Dependency implementation changes
invalidate tests through their complete runtime layout, even if the test DLL is unchanged.

Use `data_paths`, `env`, `test_working_directory`, `test_output_dirs`, and either
`test_settings` or `test_settings_output`. Bazel `--test_filter` uses the protocol's
filter; MTP can set `test_filter_argument`. Empty selections fail unless
`allow_empty_tests` is explicit. MTP/VSTest collect TRX and normalize Bazel XML;
failed/crashed/timed-out runs or missing/malformed results fail. Sharding is unsupported.
See [test attributes](../msbuild/private/test_options.bzl).

## Caching and workers

Unchanged graphs can hit Bazel's action cache. Changed graphs need a persistent
worker or HTTP project cache to reuse project snapshots; a fresh local action starts
empty. Evaluations and declared-byte verification remain fresh. Dependency keys are
conservative unless reviewed reference boundaries and runtime-copy contracts are explicit.
Task/analyzer edges consume implementation bytes.

On qualified Linux, set `linux_stable_paths = True, linux_worker = True` on
`app_graph`, then use `--strategy=MSBuildGraph=worker --worker_sandboxing`.
Each request starts fresh MSBuild inside Bubblewrap; the worker retains caches.
Prepared Restore requires matching contract/runner/SDK and stable paths.
`worker_cache_mb` defaults to 4096 logical MiB (not an RSS cap); profiling is off.

Bazel's `--remote_cache` and the plugin's HTTP AC/CAS transport have separate keys.
Set `--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=http://cache:9090` for the latter.
If needed, pass `RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN` from the environment.
Missing blobs cause rebuilds; corruption fails; transfers are checked and retried.
HTTP publication has no atomic compare-and-swap guarantee for divergent writers.
See [support limits](support.md) before assuming hermeticity or remote execution.
