# MSBuild graph-cache migration

## Direction

The intended primary build is one Bazel action per MSBuild traversal graph.
MSBuild keeps project evaluation, SDK targets, NuGet behavior, and graph
scheduling. A `ProjectCachePluginBase` implementation checks each configured
project before MSBuild builds it. Bazel still declares the graph action's
source, SDK, package, tool, and output inputs. Its ordinary action cache can
reuse an unchanged whole graph; the project cache handles edits within that
graph.

The current per-project Bazel rules remain the default during migration.
Their input and output contracts cover cases the graph plugin does not yet
cover. Replacing them before those contracts are transferred risks incorrect
cache hits.

## First cache handoff

The test-only graph probes can use `RULES_MSBUILD_PROJECT_CACHE_URL` to read
and publish project snapshots through the same HTTP cache service Bazel uses.
Each project fingerprint gets a domain-separated action-cache key. The
manifest and owned files are stored by digest in the CAS. The action-cache
entry is a valid `ActionResult` pointing to the manifest, so the pinned
`bazel-remote` server retains its normal validation. Every downloaded blob is
hashed again before replay. This is a separate client of the cache service;
Bazel itself still sees a whole-graph action.

The bounded Bazel qualification builds two independent three-project graph
actions with no fixed seed target. The Base action published three snapshots;
the body-edited action fetched two and rebuilt one. A no-cache action rebuilt
all three. The edited app ran with the new value, and each project's captured
outputs matched the no-cache control. A standalone qualification also
replayed the edited graph at a third workspace path with three hits and
compared its outputs with the edited build. Run with a pinned SDK and local
cache service:

```sh
RULES_MSBUILD_DOTNET_ROOT=/absolute/path/to/pinned/sdk \
  python3 tests/explicit_msbuild/cache_extension/qualify_remote.py \
  http://127.0.0.1:9090
RULES_MSBUILD_DOTNET_ROOT=/absolute/path/to/pinned/sdk \
  python3 tests/explicit_msbuild/cache_extension/qualify_bazel_remote.py \
  http://127.0.0.1:9090
```

On macOS ARM64 with SDK 10.0.400, Bazel 9.2.0, and pinned `bazel-remote`
2.6.2, one Bazel run reported 0/3 hits/misses for Base, 2/1 for the body
edit, and 0/3 for the no-cache control. With shared C# compilation disabled,
the probe process took 1.86, 0.90, and 1.79 seconds respectively. These are
probe times inside actions, not end-to-end Bazel build times or a performance
comparison with the existing rules. The Bazel qualification used a local
execution strategy so the action could reach the loopback cache service.

Repeated standalone runs exposed DLL/PDB hash differences when the fixture
root used macOS's `/var` alias. The compiler wrote the physical
`/private/var/.../base` or `/private/var/.../edit` source path into portable
PDBs, while the probe's `PathMap` used `/var/...`. A different output could
therefore have the same project fingerprint. The store now rejects a
conflicting existing entry instead of overwriting it. The probe resolves the
physical workspace path before graph evaluation and versioned its fingerprint
to avoid old entries. The reproduced alias case failed before this change;
eleven alias-path runs passed afterward, and both inspected PDBs contained
`/_/workspace/...` paths. `qualify_remote.py` keeps exact-output assertions
and reports any fresh cross-path differences.

## Orchard check

The same transport was added to the test-only Orchard profile. A disposable
copy of Orchard Core at `04467a3438d4255627c1a478598a1585b3ff2947`
used the CMS entry point, SDK 10.0.400, Release `net10.0`, four MSBuild
nodes, disabled shared C# compilation, and 403 graph nodes. The final remote
seed took 128.26 seconds,
including publishing its snapshots. A clean remote replay hit all 202
configured projects; all 16,448 captured `bin/Release` and `obj/Release`
files matched the seed. The setup page and three embedded assets served from
the replayed output.

A run against the populated cache measured 9.73 seconds for clean replay,
11.27 seconds for the Abstractions body edit (201 configured hits and one
configured miss), 87.07 seconds for a deliberately forced no-cache control,
and 9.72 seconds for replay from the derived entries after deleting the local
seed. The edited project's DLL, PDB, and reference assembly matched
the control, and both edited builds served matching assets. As in the earlier
local-seed qualification, 752 of 12,800 wider semantic output files differed
from the independent control because Orchard's interceptor generator embeds
random GUIDs. These single runs do not establish a speedup over warm raw
MSBuild. Reproduce with:

```sh
RULES_MSBUILD_DOTNET_ROOT=/absolute/path/to/pinned/sdk \
NUGET_PACKAGES=/absolute/path/to/pinned/packages \
  python3 tests/explicit_msbuild/cache_extension/qualify_orchard.py \
  /path/to/disposable/orchard /path/to/results \
  --remote-url http://127.0.0.1:9090
```

## Requirements before changing the default

1. Move the probe out of `tests/` into a generic graph runner. Its current
   fingerprint discovers selected project files, evaluated items, shared
   directories, package archives, and reference outputs for the pinned
   Avalonia, Orchard, and runtime profiles. It must account for imports,
   generated inputs, task reads, SDK and package bytes, target properties, and
   native tools generically. Unknown inputs must cause a safe miss or a
   qualification error.
2. Capture the full output closure and target results for build, test,
   publish, and generated files. The small probe now stages apphosts and
   dependency PDBs as well as DLLs. Orchard still requires broad `obj/Release`
   snapshots; path-sensitive generated output needs a stable-path contract
   before it can be shared across workers.
3. Make the graph rule consume declared source, SDK, package, and tool inputs
   through the public facade. Configure cache credentials and endpoints
   without hard-coding a loopback URL in a BUILD file. Prove a fresh worker
   can retrieve a snapshot from the shared service, validate outputs, and
   serve the app. The tests here used one macOS host and local execution.
4. Compare body, API, resource, test, and publish edits on larger graphs
   against warm raw graph-mode MSBuild and the current per-project rules.
   Earlier Avalonia and runtime probes did not beat raw graph-mode edits;
   preserving correctness alone is insufficient to justify switching the
   default. After the graph route passes, update generator and macro defaults,
   then remove the per-project compile path separately.

The remote project store currently uses no authentication, retries, batching,
or cross-process locking. A missing entry falls back to MSBuild compilation;
a malformed, corrupt, or conflicting entry fails the build. The small test is
package-free, and Orchard's input discovery remains profile-specific. Neither
run proves general remote-cache correctness or remote execution.

## Generic runner migration checkpoints

`tools/GraphBuild` starts with an explicit versioned input contract. Each project
lists its input files and owned output directories; shared inputs cover common
props and targets. Evaluation rejects missing project declarations, undeclared
imports and common SDK file items, missing declared files, symlinks, and overlapping
outputs. Task reads that evaluation cannot discover remain the declaration
caller's responsibility, as with other Bazel actions. This is not file-access
tracing and does not qualify arbitrary custom tasks.

The fingerprint hashes the selected SDK tree once per invocation, project and
shared inputs, global properties, and output declarations. It includes physical
workspace and SDK paths: generic cross-path output portability is not yet proven.
Fresh workers must use the same paths until that contract is qualified. NuGet
restore products must be explicit inputs; package resolution is not inferred.

Run the bounded contract checks after building `tools/GraphBuild/GraphBuild.csproj`:

```sh
RULES_MSBUILD_DOTNET_ROOT=/path/to/pinned/sdk python3 tests/graph_build/qualify.py
```

On macOS ARM64 with SDK 10.0.400, source/import invalidation, undeclared-import
rejection, and overlapping-output rejection pass. This first checkpoint inspects
contracts; it does not replace the production build rules.

The generic runner now executes `Build` and `Publish`, stores their actual target
items and custom metadata, and restores them through `PluginTargetResult` rather
than a `GetTargetPath` proxy. Snapshots own declared output directories, preserve
Unix permissions, validate digests before copying, and reject dirty output trees.
The disposable MSBuild `*.AssemblyReference.cache` files contain timestamps and
are excluded from snapshots and output parity comparisons.

Dependency invalidation is conservative by default. A contract may explicitly
select `ReferenceBoundary` and declare `DependencyCopies` to consume reference
assemblies for compilation while refreshing runtime copies from current producers.
Copy bindings are checked against dependency ownership and actual file digests;
the runner does not infer copy semantics from matching names or bytes.

`tests/graph_build/replay.py` passed with SDK 10.0.400 on macOS ARM64: clean replay
3/0 hits/misses, body edit 2/1, API edit 1/2, publish seed 0/3, and publish replay
3/0. The body-edited app printed the new value and its captured outputs matched a
fresh control. The fixture explicitly disables transitive compiler references;
its API edit stops after the direct consumer's reference assembly stays unchanged.
A corrupted snapshot was rejected. These are synthetic build/publish checks;
MTP/VSTest, arbitrary generated outputs, and upstream contract generation remain
cutover gates. The measured `seconds` currently covers build and snapshot work,
not SDK hashing and evaluation, and must not be used as end-to-end timing.

The opt-in public API is `msbuild_graph_runner`, `msbuild_graph`, and
`msbuild_graph_test` in `msbuild/defs.bzl`. The graph rule uses the registered SDK
toolchain, declared source files, a contract JSON file, and optional `.nupkg`
archives. Restore is offline; its generated default `obj` inputs and extracted
packages join the contract before graph evaluation. Custom restore paths are
rejected by this first automatic-restore slice. The executable test rule runs a
selected assembly and lets Bazel cache its test result. VSTest adapter selection
and MTP result-file integration are not yet qualified.

`tests/graph_build/bazel.py` passes in an independent macOS consumer: the graph
build succeeds, the executable test passes, and editing the app to return a
failure invalidates its test result. Endpoint configuration is supplied with
`--action_env=RULES_MSBUILD_PROJECT_CACHE_URL`; it is not stored in BUILD files.

Two independent Linux ARM64 containers also ran `tests/graph_build/worker.py`
with SDK 10.0.400 at `/graph-cache-qualification/sdk` and source at
`/graph-cache-qualification/workspace`. The producer published three snapshots
(0/3 hits/misses). The consumer had no local snapshots, fetched two, rebuilt the
body-edited leaf (2/1), and ran the app with the edited value using the shared
bazel-remote 2.6.2 HTTP service. These are fixed-path standalone worker runs, not
Bazel remote execution. Standard Bazel sandbox paths still differ between actions;
this generic runner safely misses across such paths. A stable execution namespace
remains necessary before claiming efficient project reuse across Bazel workers.
