# API

Follow the [quickstart](../examples/quickstart/README.md) for setup. Load build rules
from `@rules_msbuild//msbuild:defs.bzl`; load `msbuild_sync` from `@rules_msbuild//msbuild:sync.bzl`.
See [design](design.md) for ownership, graph execution and cache invalidation.

## Sync

Declare `msbuild_sync(name = "sync", projects = ["App/App.csproj"])` in the root
BUILD file. Run `bazel run //:sync` and commit `graph.generated.json` and
`graph.generated.bzl`. The generated `app_graph` macro declares the build.

For `Microsoft.Build.Traversal`, use `projects = ["dirs.proj"]`. Pin its SDK in
`global.json` (or the project), include its package in `package_lock`, and set
`package_build = True`. Nested coordinators retain Restore metadata but produce
no assemblies. Build/Pack/Publish operate on the children; declare Bazel tests for
the test projects. See [qualified traversal scope](support.md#traversal-projects).

`Microsoft.Build.NoTargets` accepts `.csproj` or `.proj` entries with the same
package-SDK setup. Declare its products in mappings `outputFiles` and attest
custom targets/tasks in `documents`. It has no assembly/runtime selector; export
products with `msbuild_graph_output`. Projects with declared products use snapshots;
empty utility projects remain uncached. Dependency edges consume implementation
inputs and products, including beneath a reviewed compiler-reference boundary.

`Microsoft.NET.Sdk.Worker` uses the normal managed graph API. Sync accepts root
SDK attributes, semicolon-separated SDK composition and top-level `<Sdk Name="…" />`
elements for qualified SDKs; MSBuild resolves their imports and versions. Unknown
SDKs remain rejected. Package/content side effects still need explicit contracts.

`Microsoft.NET.Sdk.IL` accepts `.ilproj` entries and project mappings. Declare the
pinned package SDK and native ILAsm/ILDasm packages in the closed inventory.
IL assemblies without reference assemblies use implementation dependency keys;
request deterministic assembler output explicitly (`IlasmFlags=-DET` in the
qualified fixture). See [qualified IL scope](support.md).

Compose `Microsoft.DotNet.Arcade.Sdk` with a managed SDK and lock the SDK plus
its implicit packages. Declare version/repository inputs and Pack products.
Effective `OfficialBuild` or `DotNetUseShippingVersions` requires `OfficialBuildId`;
sync rejects the ambient-date fallback. A cold Pack needs a packable root and
`GeneratePackageOnBuild=false`; that SDK setting otherwise assumes built assemblies.

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
`inputDirectories`, `temporaryDirectories`, `replayOmissions`, `referenceBoundary`,
`implementationDependencies`, `compilerReference`, `compilerReferences`,
`preparedRestore`, `restoreInputs`, and `restoreOutputs`.
`projectDefaults.properties` sets graph-wide properties. Unknown/duplicate fields
and unsafe paths fail; document changes require renewed contract review.

## Build and artifacts

| Rule | Use |
| --- | --- |
| `msbuild_graph_runner` / `msbuild_graph` | Bootstrap the runner; Build, Pack or Publish an explicit graph contract |
| `msbuild_graph_binary` / `msbuild_graph_test` | Run or test a graph's `project`, selecting `framework` if ambiguous |
| `msbuild_graph_layout` / `msbuild_graph_output` | Export a project layout, contract-owned file or directory tree |
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

Use `msbuild_graph_output(directory = True)` for an owned reference/generated tree;
map it with `input_paths = {":references": "prepared"}` in the consuming graph.
Its consumed files still need explicit contract inputs. Exports reject links.

`replayOmissions` lists reviewed disposable intermediate files, relative to the
workspace in a graph contract; sync mappings may use project property expressions.
For example, `"$(IntermediateOutputPath)$(TargetFileName)"` selects the duplicate
implementation DLL in `obj`. Omitted files stay in complete, verified snapshots
but are absent from action products after both compilation and recovery. Required
assemblies, references, declared outputs/copies and target-result paths are rejected.
Use only when tasks, downstream projects and exports do not need those files;
there are no automatic omissions. This contract is qualified for Build only.

## Tests

Executable tests may set `expected_exit_code` (0–255, default 0); for example,
CoreCLR wrappers return 100 on success. MTP/VSTest retain their own protocols.

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

`msbuild_graph_output` can also select a prepared Restore target. Those exports
use `Restore.Outputs` ownership, so generated assets/props/targets can be declared
inputs of another graph without treating package state as compilation output.
