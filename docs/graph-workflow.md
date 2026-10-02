# Graph workflow

Bazel owns declared inputs, toolchains, actions and test caching. MSBuild owns
project evaluation, configured project edges, SDK targets and compilation. One
`msbuild_graph` action builds a selected graph; the MSBuild project-cache plugin
reuses individual projects within that action. There is no per-project compiler
backend or sync mode switch.

## Application setup

Follow the [quickstart](../examples/quickstart/README.md). Select the SDK in
`global.json`, register its toolchains in `MODULE.bazel`, and declare sync:

```starlark
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")

msbuild_sync(
    name = "sync",
    projects = ["App/App.csproj", "Tests/Tests.csproj"],
)
```

Run `bazel run //:sync`, commit `graph.generated.json` and
`graph.generated.bzl`, then add:

```starlark
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary", "msbuild_graph_test")

app_graph(name = "graph")
msbuild_graph_binary(name = "app", graph = ":graph", project = "App/App.csproj")
msbuild_graph_test(name = "tests", graph = ":graph", project = "Tests/Tests.csproj")
```

`bazel run //:app` and `bazel test //:tests` share the graph action. Their extracted
runtime layouts contain the selected project's SDK-composed output. A dependency
implementation edit can rerun its tests even if the test assembly bytes stay equal.
An unrelated project edit can leave the selected test's layout and result cached.

## Rules

| Rule | Purpose |
| --- | --- |
| `msbuild_graph_runner` | Bootstrap the graph engine from the declared execution SDK |
| `msbuild_graph` | Build or Publish a contract-declared project graph |
| `msbuild_graph_restore` | Produce offline Restore state for a matching stable-path graph |
| `msbuild_graph_binary` / `msbuild_graph_test` | Run/test one generated project and optional framework |
| `msbuild_graph_layout` | Export a project's complete runtime or Publish directory |
| `msbuild_graph_output` | Export one file from a declared graph output directory |
| `msbuild_tool` / `msbuild_file_binding` | Bind a complete execution-layout entry point to an MSBuild property |
| `msbuild_layout` / `msbuild_runtime` | Compose declared artifacts and select an execution host |
| `msbuild_nuget_package` / `msbuild_generated_nuget_package` | Validate acquired/generated NuGet archives and extract them |
| `msbuild_package_lock` / `msbuild_nuget_dependencies` | Form explicit closed package inventories |
| `msbuild_test_tool` | Select a VSTest runner or adapter from a locked package |
| `msbuild_native_toolchain*` | Acquire native tool archives or locked package inputs |

`msbuild_native_tool` uses the same complete-layout contract as `msbuild_tool`.
Downloaded and source-built SDKs share [the SDK artifact contract](sdk-toolchains.md).
Source-built execution hosts use `msbuild_runtime` and `runtime_host`; compilation
SDK and application host are separate selections.

## Graph inputs

The generated JSON contract identifies projects by path and global properties.
Each project declares input files, owned output directories/files, and any reviewed
reference-boundary, implementation-dependency or dependency-copy contracts. Shared
inputs cover common props/targets. Sync transfers evaluated SDK semantics into this
contract; it does not translate arbitrary custom tasks into Starlark.

The rule's `srcs`, `input_paths`, `bindings`, `packages` and `package_lock` supply
those files. `source_root` removes a known Bazel package prefix. `input_paths`
assigns logical paths to single-file producer labels. Paths must be relative and
safe. Symlinked input discovery, missing declarations, conflicting ownership and
changed definition digests fail explicitly. Task reads invisible to evaluation
still require caller declarations; this is not file-access tracing.

Handwritten contracts are supported for small fixtures. A manually authored graph
also supplies `project_outputs` / `publish_outputs`: keys are `project|framework`,
values are `[directory, assembly_filename, output_type]`. Prefer generated selectors
for ordinary applications. Run/test selection must identify one configuration.

## Restore and packages

NuGet inventories include exact versions, transitive dependencies, SHA-256 archive
hashes and NuGet content hashes. Graph actions consume the original archives and
restore offline. SDK package imports also require this closed inventory.
`allow_multiple_versions = True` on a package lock permits configured graphs that
need distinct versions of an ID. No ambient feed or user package cache supplies
missing inputs.

Set `package_build = True` on sync to evaluate package targets/content after offline
Restore in an owned disposable copy. Declare extra task reads in `package_inputs`;
reviewed document/input contracts remain required. See [sync](project-sync.md).

Prepared Restore is a separate graph action using the same contract, runner and SDK.
It requires `linux_stable_paths = True`. Contract-declared Restore inputs and outputs
control reuse; compilation verifies the preparation fingerprint before consuming it.
A whole-action Bazel hit avoids execution. A project-cache hit restores declared
products and real MSBuild target results after current input verification.

## Tools and generated packages

Build a task or analyzer through its own graph, export its runtime directory, then
bind the complete layout. Dependencies and data must already be in that layout. A managed task library can
use the SDK's `CopyLocalLockFileAssemblies` to include its package dependencies:

```starlark
msbuild_graph_layout(name = "tasks_layout", graph = ":tasks_graph", project = "Tasks/Tasks.csproj")
msbuild_tool(name = "task", layout = ":tasks_layout", entry_point = "Tasks.dll")
msbuild_file_binding(name = "binding", tool = ":task", property_name = "TaskLocation")
```

Pass `bindings = [":binding"]` to sync and its generated graph. Binding content
changes invalidate consumers without resync; changing the property/entry contract
requires resync. Tools use the execution configuration and complete layouts; there
is no separate transitive dependency replay/staging rule.

For SDK Pack, declare the package directory in the graph contract and retain the
SDK's Pack behavior, for example `GeneratePackageOnBuild` in the project. Export
its `.nupkg` with `msbuild_graph_output`, then use `msbuild_generated_nuget_package`.
Generated packages require action outputs; downloaded packages require fixed hashes.

## Cache and invalidation

An unchanged graph can hit Bazel's whole-action cache. A changed action reuses
project snapshots only with a persistent graph worker or the HTTP project cache;
a fresh local action otherwise starts with an empty project cache.

The plugin fingerprints current declared bytes, evaluated properties/items, SDK
and runner identity, output contracts and dependency roles. Evaluation remains
fresh per invocation. It rejects declared inputs changed during execution.

Dependency invalidation is conservative unless a reviewed reference boundary is
explicit. If C's API changes, B rebuilds. A may reuse its compilation if B's reference
assembly stays unchanged and the declared copy bindings refresh runtime dependencies.
Task/analyzer/implementation edges consume implementation bytes. Shared binplace
and custom generators need explicit ownership and input contracts.

## Linux workers

```starlark
app_graph(name = "graph", linux_stable_paths = True, linux_worker = True)
```

Use `--strategy=MSBuildGraph=worker --worker_sandboxing` with the
[qualified Linux environment](linux-workers.md). The persistent process retains
verified preparation/snapshot caches; each request starts fresh isolated MSBuild.
`worker_cache_mb` is a logical cache budget, not an RSS limit (default 4096).
Profiling is off by default. `profile_build = True` records diagnostics and changes
the action; do not use diagnostic timings as benchmark scores.

## Migration

The former library/binary/project facades, per-project compiler/worker and generator
were removed. Regenerate declarations with sync and select graph projects for
run/test/layout. Replace assembly-based tool bindings with complete graph layouts.
Old mappings are rejected rather than silently ignored. Commands and measurements
for the retired backend are in [history](history.md).

See [current support](implementation-plan.md) for measured scope and remaining gaps.
