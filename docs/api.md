# API

Start with the [quick start](../examples/quickstart/README.md). Load rules from
`@rules_msbuild//msbuild:defs.bzl`, sync from `@rules_msbuild//msbuild:sync.bzl`,
and SDK declarations from `@rules_msbuild//msbuild:sdk.bzl`. [Design](design.md) explains ownership and invalidation.

## Sync

```starlark
msbuild_sync(name = "sync", projects = ["App/App.csproj"])
```

Run `bazel run //:sync`; commit `graph.generated.json` and `graph.generated.bzl`.
The generated `app_graph` macro declares the graph. Body edits build normally;
rerun sync after project/import, source-list, package or configuration changes.
Use `bazel run //:sync -- --check` to reject stale declarations.

Sync can shorten local C# input lists with checked, nonrecursive globs. It retains
expected filenames and emits globs only when they match evaluated inputs and reduce
the declaration size. In globbed directories, additions, removals and renames fail
graph analysis until sync; body edits build normally, and sync remains runnable. JSON
inputs stay explicit. Exclusions, produced inputs and package boundaries keep their
existing contracts; this does not enable automatic source membership.

| Attribute | Use |
| --- | --- |
| `projects` | Entry `.csproj`, `.ilproj` or Traversal/NoTargets `.proj` paths |
| `configuration`, `framework` | Release by default; optional entry framework |
| `inputs` | Single-file producer labels mapped to workspace-relative paths |
| `package_lock`, `package_locks` | Closed package inventories, including package SDKs |
| `package_build`, `package_inputs` | Offline Restore/package evaluation; extra declared task reads |
| `resolve_references` | Private Build to capture complete compiler/copy selections; requires `package_build` |
| `bindings` | Complete tool layouts bound to MSBuild properties |
| `mappings` | Reviewed JSON contracts for custom inputs, outputs and dependency roles |

For Traversal/NoTargets/IL/Arcade, lock the SDK and implicit/native packages, set
`package_build = True`, and declare custom tasks/products. Unknown SDKs fail.
[Support](support.md#qualified-sdks) lists SDK-specific requirements and limits.

### Compiler selections

`msbuild_sync(..., package_build = True, resolve_references = True)` runs offline
Restore and Build in a disposable workspace, then captures the DLLs and copy sources
selected by the SDK at supported C# reference boundaries. Multi-target selection
uses configured producer ownership. Failed qualification, undeclared inputs,
ambiguous producers or conflicting manual bindings leave existing contracts intact.
Ordinary builds consume the contract; `--check` repeats qualification.

Complete inventories exclude unselected compiler edges from invalidation while
retaining graph execution and noncompiler dependency roles. New snapshots verify
`ReferencePathWithRefAssemblies`; SDK and declared package/file inputs keep their
byte hashes. Custom task reads and Pack/Publish-specific selections still need
contracts. Unsupported boundaries retain conservative keys.

### Mappings

Use `projectDefaults`, project-path `projects`, `frameworkOverrides`, and root
`entryProperties`; graph-wide properties go in `projectDefaults.properties`.
Unknown/duplicate fields, unsafe paths and changed document attestations fail.

| Contract fields | Purpose |
| --- | --- |
| `documents`, `inputItems`, `evaluationItems` | Attested target/task documents and extra reads |
| `inputDirectories`, `temporaryDirectories`, `outputFiles` | Input trees, private scratch and owned products |
| `preparedRestore`, `restoreInputs`, `restoreOutputs` | Separate declared Restore action |
| `referenceBoundary`, `implementationDependencies` | Qualified compiler boundary; conservative task/tool edges |
| `compilerReference`, `compilerReferences`, `compilerReferencesComplete` | Producer artifact, consumer selections and complete-inventory assertion |
| `dependencyCopies` | Consumer DLL/PDB/XML destinations mapped to graph/locked-package sources |
| `evaluationReuseInputs`, `replayOmissions` | Reviewed compiler-only inputs and disposable intermediates |

Manual `compilerReferencesComplete: true` requires `referenceBoundary: true` and
all project DLLs selected by the SDK. Partial maps retain conservative transitive
keys. Implementation DLLs belong in `compilerReferences` when Csc reads them;
additional task/tool reads belong in `implementationDependencies`.

`dependencyCopies` accepts MSBuild expressions; package sources require prepared
Restore. It describes replay; MSBuild still chooses build copies. Omitted files
remain stored and verified in snapshots. Required references, outputs, copies and
target-result paths cannot be omitted; this contract is qualified for Build only.

## Build and artifacts

| Rule | Use |
| --- | --- |
| `msbuild_graph_runner`, `msbuild_graph` | Runner bootstrap; Build, Pack or Publish a graph |
| `msbuild_graph_binary`, `msbuild_graph_test` | Run/test a `project`; choose `framework` if ambiguous |
| `msbuild_graph_layout`, `msbuild_graph_output` | Export a layout, owned file or directory tree |
| `msbuild_graph_restore` | Prepare offline Restore for a matching stable-path graph |
| `msbuild_tool`, `msbuild_file_binding`, `msbuild_native_tool` | Bind complete task/native-tool layouts |
| `msbuild_layout`, `msbuild_runtime` | Compose artifacts and describe an execution host |
| `msbuild_nuget_package`, `msbuild_generated_nuget_package` | Validate/extract acquired or produced packages |
| `msbuild_nuget_dependencies`, `msbuild_package_lock` | Declare closed package inventories |
| `msbuild_test_tool`, `msbuild_native_toolchain*` | Select package test tools and native toolchains |

Handwritten graphs supply `contract`, `srcs`, and optional `input_paths`, `bindings`
and `packages`/`package_lock`. `source_root` removes a Bazel package prefix.
Contracts identify project paths plus global properties. Runtime selectors in
`project_outputs`/`publish_outputs` map `project|framework` to
`[directory, assembly_filename, output_type]`. See [attributes](../msbuild/graph.bzl).

NuGet inventories include exact versions, transitive dependencies and archive/content
hashes. Restore is offline; user caches/feeds do not fill missing inputs.
`allow_multiple_versions = True` allows distinct configured versions. For Pack,
declare/export the `.nupkg` and consume it with `msbuild_generated_nuget_package`.

Task/analyzer layouts must include their dependencies/data:

```starlark
msbuild_graph_layout(name = "tasks_layout", graph = ":tasks_graph", project = "Tasks/Tasks.csproj")
msbuild_tool(name = "task", layout = ":tasks_layout", entry_point = "Tasks.dll")
msbuild_file_binding(name = "binding", tool = ":task", property_name = "TaskLocation")
```

Pass bindings to sync and the generated graph. Content edits invalidate consumers;
property/entry-point changes require sync. Use `msbuild_graph_output(directory = True)`
plus `input_paths` for produced trees; consumed files still need contract inputs.
Prepared Restore exports use `Restore.Outputs` ownership. Exports reject links.

`msbuild_sdk` describes a complete downloaded or produced layout rooted beside
`dotnet`; register `<name>_registered` and `<name>_runtime_registered`. The producer
needs a separate bootstrap toolchain. Host-path SDK repositories are unsupported.
`runtime_host` selects a declared `msbuild_runtime` (`dotnet` or `corerun`) independently
of compilation. Newer hosts run older targets only when runtimeconfig allows it.

## Tests

`test_protocol` is `executable` (default), `mtp` (direct execution), or `vstest`
(declared `test_runner`/`test_adapters` from locked packages; requires a dotnet host).
Executable tests use `expected_exit_code` (0–255, default 0); CoreCLR often uses 100.
MTP needs no separate runner. Dependency implementation changes invalidate tests
through their complete runtime layout, even if the test DLL is unchanged.

Use `data_paths`, `env`, `test_working_directory`, `test_output_dirs`, and
`test_settings` or `test_settings_output`. `--test_filter` uses the selected protocol;
MTP can set `test_filter_argument`. Empty selections fail unless `allow_empty_tests`
is explicit. MTP/VSTest collect TRX and normalize Bazel XML. Failures, crashes,
timeouts and missing/malformed results fail. Sharding is unsupported.
See [test attributes](../msbuild/private/test_options.bzl).

## Caching and workers

Bazel caches unchanged graph actions. Changed graphs need a Linux persistent worker
or HTTP project cache to reuse snapshots; a fresh local action starts empty.
Set `linux_stable_paths = True, linux_worker = True` on `app_graph`, then use
`--strategy=MSBuildGraph=worker --worker_sandboxing`. Bubblewrap supplies stable paths
and fresh build nodes. See [platform limits](support.md#limits).

`worker_cache_mb` defaults to 4096 logical MiB; `evaluation_cache_mb` defaults to
512 MiB and zero disables retention. These are retention limits, not peak RSS caps.
Profiling is off by default. Reviewed `evaluationReuseInputs` (paths or `@(Compile)`)
can retain evaluation with prepared Restore and stable workers. Other input,
configuration or membership changes and failures reset it. Byte verification remains
fresh; arbitrary evaluation-time external/process reads cannot be retained safely.

Enable both cache levels against a trusted HTTP AC/CAS service:

```sh
bazel build //:graph --remote_cache=http://cache:9090 \
  --action_env=RULES_MSBUILD_PROJECT_CACHE_URL=http://cache:9090 \
  --remote_download_outputs=all
```

Use the worker flags above for local retention. The two caches have separate keys;
Restore action hits skip preparation. SDK/package acquisition is separate.
If needed, pass `RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN` from the environment.
Missing blobs rebuild; corruption fails; transfers are checked/retried.
HTTP publication has no atomic guarantee for divergent writers. Cache recovery
is not remote execution or proof of filesystem hermeticity.
