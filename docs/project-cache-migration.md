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

## Default-switch review

The default switch is **not ready**. The new generic path is opt-in. Replacing
`msbuild_project` and project-sync output now would remove existing supported
capabilities. The remaining work is:

1. Extend the qualified native-tool, reference-role and generated-output contracts
   to remaining custom item handoffs and upstream native/publish workflows.
   Managed/native tools, analyzer references, aliases and shared output files
   now have focused regression coverage.
2. Expand runtime beyond the qualified System.IO.Pipelines managed slice. Shared
   binplace replay passes there; full native runtime/SDK construction and use of
   that runtime through the generic graph still need end-to-end qualification.
3. Close Orchard's conservative invalidation gap. Its body-edit comparison
   rebuilds 193 of 202 projects; existing test-only plugin timings do not describe
   this public generated contract. See [current measurements](performance.md).
4. Qualify upstream relocated replay on Linux with the intended native sandbox
   and worker combination. Synthetic remote replay passes through public Bazel
   8/9 actions, but the Apple container cannot run native linux-sandbox.
5. Extend paired comparisons to upstream tests, publish and runtime edits.
   Avalonia.Controls body/API/generator output comparisons pass; Orchard retains
   generator and intermediate-cache output differences.

Once these gates pass, change generator and facade defaults in one commit, then
remove the per-project compilation path in a separate commit. No default or
legacy-path removal is claimed by the current migration checkpoints.

The shared transport supports bearer authentication, bounded parallel transfers,
three-attempt retries for transient failures, and digest-checked atomic downloads.
Missing or evicted blobs become misses and are repaired after compilation.
Malformed, corrupt, or conflicting entries fail the build. Publication compares
the entire manifest, including target metadata and permissions. The HTTP service
does not provide an atomic compare-and-swap operation for concurrent divergent
writers; conflict detection is limited to entries observed before publication.
The Orchard profile remains test-only and does not establish generic remote
execution support.

## Generic runner migration checkpoints

`tools/GraphBuild` starts with an explicit versioned input contract. Each project
lists its input files and owned output directories; shared inputs cover common
props and targets. Evaluation rejects missing project declarations, undeclared
imports and common SDK file items, missing declared files, symlinks, and overlapping
outputs. Task reads that evaluation cannot discover remain the declaration
caller's responsibility, as with other Bazel actions. This is not file-access
tracing and does not qualify arbitrary custom tasks.

The fingerprint hashes the selected SDK tree once per invocation, project and
shared inputs, evaluated properties and item metadata, runner bytes, and output
declarations. Cache endpoint and bearer credentials are removed from the MSBuild
environment before evaluation. Evaluated fingerprints are frozen before execution;
a build that changes a declared input is rejected. It includes physical
workspace and SDK paths: generic cross-path output portability is not yet proven.
Fresh workers must use the same paths until that contract is qualified. NuGet
restore products must be explicit inputs; package resolution is not inferred.

Run the bounded contract checks after building `tools/GraphBuild/GraphBuild.csproj`:

```sh
RULES_MSBUILD_DOTNET_ROOT=/path/to/pinned/sdk python3 tests/graph_build/qualify.py
```

On macOS ARM64 with SDK 10.0.400, source/import invalidation, undeclared-import
rejection, and overlapping-output rejection pass. This remains an opt-in build
path; the existing facade and generator defaults have not changed.

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
3/0 hits/misses, body edit 2/1, API edit 1/2, resource edit 0/3, publish seed
0/3, and publish replay 3/0. The body-edited app printed the new value and its captured outputs matched a
fresh control. The fixture explicitly disables transitive compiler references;
its API edit stops after the direct consumer's reference assembly stays unchanged.
A corrupted snapshot was rejected. These are synthetic build/publish checks;
MTP/VSTest, arbitrary generated outputs, and upstream contract generation remain
cutover gates. Reports now separate evaluation, input hashing, build/snapshot
work, and total process time. Earlier `seconds` reports excluded evaluation and
hashing and are not end-to-end comparisons.

The opt-in public API is `msbuild_graph_runner`, `msbuild_graph`, and
`msbuild_graph_test` in `msbuild/defs.bzl`. The graph rule uses the registered SDK
toolchain, declared source files, a contract JSON file, and optional `.nupkg`
archives. Restore is offline; its generated default `obj` inputs and extracted
packages join the contract before graph evaluation. Custom restore paths are
rejected by this first automatic-restore slice. The executable test rule runs a
selected assembly and lets Bazel cache its test result. VSTest adapter selection
and MTP result-file integration are not yet qualified.

`tests/graph_build/bazel.py` passes on Bazel 8.8.0 and 9.2.0 in an independent
macOS consumer: the graph
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

After removing the consumer workspace and local snapshots again, the derived
entries replayed with 3/0 hits/misses. A fresh no-cache Linux control matched all
54 captured files byte-for-byte (excluding the disposable assembly-resolution
cache), and the native apphost ran with the edited value.

`tests/graph_build/remote.py` injects authenticated HTTP requests, two transient
503 failures, concurrent transfers, an evicted CAS blob, and a corrupt CAS blob.
All controls pass. The existing `qualify_remote.py` probe also passes with the
hardened transport and reports no cross-path output mismatches in its bounded
fixture. Neither test simulates distributed conflicting publishers.

The generic runner caches evaluated fingerprints, declared input digests,
dependency reachability, output inventories, and completed dependency digests
within one invocation. Copy-binding validation uses declared directory ownership
instead of repeatedly walking transitive output trees.

## Generic edit timing

Command: `tests/graph_build/benchmark.py --projects 128 --samples 3`, with
`RULES_MSBUILD_DOTNET_ROOT` set to SDK 10.0.400. On macOS ARM64, both engines used
Release, four MSBuild nodes, disabled shared compilation, and explicitly disabled
transitive compiler references. The cache runner removed build outputs before
each invocation and reused local project snapshots; raw MSBuild retained its
incremental outputs. Restore ran before timing. These are complete process wall
times, including graph evaluation, fingerprinting, and snapshot handling, but
exclude Bazel startup, Restore, and remote transfer. This is a synthetic serial
chain, not an Orchard/runtime performance claim.

| Edit | Generic runner median | Warm raw graph-mode MSBuild | Cache hits/misses |
| --- | ---: | ---: | ---: |
| Body | 6.88 s | 6.93 s | 127/1 |
| API | 7.37 s | 7.21 s | 126/2 |

Before eliminating repeated transitive output scans, the corresponding runner
medians were 13.63 s and 14.13 s. The final body runs spent about 2.77 s evaluating
and validating the graph, 0.85 s hashing inputs and evaluated state, and 3.21 s
building and handling snapshots. The remaining cost is no longer dominated by
repeated dependency-tree enumeration. This reaches roughly raw MSBuild time in
the synthetic case; larger real-project comparisons through the generic rule
remain required before changing the default.

## Configured graph contracts

Version 1 contracts remain supported. Version 2 adds optional `Configurations`
per project. Each configuration supplies `Properties` selectors, `Inputs`,
`OutputDirectories`, and optional `ReferenceBoundary` / `DependencyCopies`.
Project-level inputs are shared by its configurations; output ownership stays
inside each configuration. Exactly one selector must match the node's global
properties. An empty selector value matches an absent property, such as
`TargetFramework` on a multi-targeted outer node. Declare no outputs for that
outer node. The runner rejects ambiguity, missing matches and overlapping output
ownership.

`action` adds the evaluated `ProjectAssetsFile` and NuGet-generated props/targets
under `MSBuildProjectExtensionsPath` to each selected configuration's inputs.
These files must exist inside the workspace. This uses the graph's existing
evaluation, without evaluating projects again to discover restore paths.

Qualification on macOS ARM64, SDK 10.0.400:

```sh
RULES_MSBUILD_DOTNET_ROOT=/absolute/path/to/pinned/sdk \
  python3 tests/graph_build/configurations.py
```

The package-free `net10.0;net10.0-windows` library builds both inner nodes, then
replays both after deleting build outputs. The same check passes with restore
files under a custom extensions directory, with the intermediate tree fully
removed between actions. Leaving an empty `obj` directory changed evaluated
backslash/slash spelling on this SDK and conservatively missed the cache.
Ambiguous/missing selectors,
overlapping outputs, and configuration declarations in version 1 are rejected.
This proves contract selection and custom restore layout, not Windows execution
or package-rich multi-targeting.

## Opt-in graph synchronization

For a supported `Microsoft.NET.Sdk` graph, keep the existing `msbuild_sync`
target, set `mode = "graph"`, and run:

```sh
bazel run //:sync
bazel run //:sync -- --check
```

Sync writes `graph.generated.json` and `graph.generated.bzl`. Add this to the
root BUILD file:

```starlark
load(":graph.generated.bzl", "app_graph")

app_graph(name = "app")
```

The generated contract declares evaluated source files, imports, configuration
selectors and output directories. Ordinary library dependencies use reference
assemblies for compilation identity and explicit DLL/PDB/XML copy bindings for
current runtime files. Content/resource copying, custom reference roles and
specialized publish settings retain conservative invalidation.
Sync accepts exact package references from a declared `package_lock`. Package
build/content evaluation requires `package_build = True`. It rejects
legacy test-runner mappings and external assembly references. Reviewed custom
targets/tasks and generated files use the graph mappings described below. Run sync for the intended SDK/platform; this
slice does not translate host-specific conditions into Bazel platform selectors.
The default per-project sync output is unchanged.

On macOS ARM64 with SDK 10.0.400 and Bazel 9.2.0, these passed:

```sh
python3 tests/graph_build/sync.py
python3 tests/graph_build/bazel.py --sync
```

The first uses generated contracts for three-project build/replay, freshness and
rejection controls, and a two-framework library. The second invokes the public
Bazel sync target, builds the generated graph, runs an executable test, then
checks that editing it to fail invalidates the cached test result. Set the pinned
SDK/Bazelisk wrapper overrides when they are not installed in this checkout.

## Package generation and Linux follow-up

```sh
RULES_MSBUILD_DOTNET_ROOT=/absolute/path/to/pinned/sdk \
  python3 tests/graph_build/packages.py
```

This fixture locally packs two versions of a managed library with a
`buildTransitive` target that generates compiled source. The generic action
restores only from its declared package archive directory. Each run recreates
the workspace and restores packages again. Both the package DLL and generated
source are present after replay; upgrading the archive/version causes a miss.
The upgraded build, replay and fresh-cache control have byte-identical captured
outputs, excluding the disposable `AssemblyReference.cache` file.

`configurations.py`, `sync.py` and `packages.py` passed on both macOS ARM64 and
the existing Ubuntu ARM64 qualification container with SDK 10.0.400. Both .NET
tools built without warnings. The existing project-sync unit suite also passed
all 53 tests on macOS. These checks establish small standalone graph slices;
broader package-aware sync, Linux Bazel stable paths, large package-rich graphs, native
tasks and MTP/VSTest integration are still unqualified.

## Copy-on-write measurement

The existing `File.Copy` path already attempts COW on supported platforms:
see the [.NET Unix implementation](https://github.com/dotnet/runtime/blob/v10.0.0/src/libraries/System.Private.CoreLib/src/System/IO/FileSystem.Unix.cs)
and [Linux FICLONE fallback](https://github.com/dotnet/runtime/blob/v10.0.0/src/native/libs/System.Native/pal_io.c).
Explicit `clonefile`/`FICLONE` is available as a measurement override; unsuccessful
clones fall back to `File.Copy`. No hard links are used. The default remains
`File.Copy`.

Run the paired synthetic with `--copy-mode copy` or `--copy-mode clone`:

```sh
python3 tests/graph_build/benchmark.py --projects 128 --samples 3 --copy-mode copy
python3 tests/graph_build/benchmark.py --projects 128 --samples 3 --copy-mode clone
```

On macOS ARM64, SDK 10.0.400, three samples per edit gave:

| Mode | Body wall time | Body materialization | API wall time |
| --- | ---: | ---: | ---: |
| .NET File.Copy | 7.03 s | 1.71 s | 7.53 s |
| Explicit clone | 6.74 s | 1.48 s | 7.26 s |

Every body run materialized 18,179 files, totaling 129,414,775 logical bytes.
All explicit clone attempts succeeded. The explicit path saved about 0.29 s
(4%) overall and 0.24 s in materialization. These are local-cache process times,
excluding restore, Bazel and remote transfers, with profiling enabled. The
prototype applied destination cleanup in both modes; the default path keeps
its original overwrite behavior. Three samples do not establish a broad workload
speedup, and this is not a comparison against forced byte-by-byte copying.

`RULES_MSBUILD_GRAPH_COPY_MODE=clone` selects the experiment for the standalone
runner. `RULES_MSBUILD_GRAPH_PROFILE=1` enables materialization counters (also
set by the benchmark). Profiling is off by default. Both settings are removed
before MSBuild evaluation so they do not change cache identity. `copies` counts
calls to `File.Copy`, which may themselves clone; `bytes` counts logical file
lengths, not physical bytes transferred. Materialization seconds sum operation
durations and can overlap in a parallel graph. The replay qualification writes
through a restored dependency and verifies that producer and cached DLLs remain
unchanged, then checks body/API/resource/publish parity.

## Generated dependency invalidation

For qualified package-free SDK library references, sync now emits
`ReferenceBoundary` plus `DependencyCopies` for build and publish directories.
A body edit can reuse consumers while refreshing their dependency DLL, PDB and
XML files. Presence of optional copy outputs is part of the fingerprint, so
adding or removing documentation/symbol files cannot replay an obsolete output
set. Nonstandard symbol/documentation paths retain conservative invalidation.
Ambiguous destination names fail synchronization. Content/resource
inputs, implementation/custom-reference roles, executable dependencies and
trimmed/AOT/ReadyToRun/single-file publishing retain conservative invalidation.

Reference identity also includes transitive reference assemblies when SDK
transitive compiler references are enabled. With `A -> B -> C`, an unchanged B
reference assembly stops C's API invalidation at B only when A cannot directly
compile against C. The generator does not change that SDK setting. Generated contracts also carry
`DefinitionDigests` for authored project/import files. The runner requires sync
after those files change, before evaluation; C# source edits do not require sync.
This prevents old optimized declarations from surviving a changed project
contract, such as newly added content-copy metadata or custom targets.

```sh
python3 tests/graph_build/invalidation.py
```

The three-project qualification runs with transitive compiler references both
on and off. A body edit gets 2 hits / 1 miss and refreshed runtime/XML copies.
An API edit gets 1/2 when transitive references are disabled and 0/3 when enabled.
A subsequent B API edit rebuilds B and A. Publish body edits also get 2/1; their
captured outputs match fresh-cache controls. Removing and restoring a dependency
XML output invalidates or reuses the matching output shape correctly. A stale
project definition is rejected until sync. Adding copy-to-output content
switches back to conservative behavior and propagates edited data correctly.
These are generated standalone contracts at a stable workspace path, not
qualification of project-cache hits across ordinary Bazel sandbox paths.

With the generated-contract benchmark (`--generated`, 32 projects, three paired
samples on macOS ARM64), disabling these declarations with `--conservative`
reproduces the earlier generator behavior:

| Edit | Conservative contracts | Reference boundaries | Raw MSBuild alongside boundaries |
| --- | ---: | ---: | ---: |
| Body | 16.51 s (0/32 hits/misses) | 2.13 s (31/1) | 2.10 s |
| API | 16.67 s (0/32) | 2.60 s (30/2) | 2.62 s |

Both runs use the default .NET copy path and profiling, with transitive compiler
references explicitly disabled for the chain. The body improvement is about
7.7x over the old generated declarations; it brings this slice close to warm raw
MSBuild. It is separate from the 128-project copy-mode comparison above, whose
handwritten contracts already used reference boundaries. Restore runs before
timing; cached builds recreate outputs while raw builds retain incremental state.

The invalidation fixture passed on macOS ARM64 and the Ubuntu ARM64 container.
The explicit-clone replay fixture also passed on both. Linux reported 0 clones
and 54 fallbacks for replay/body on its current filesystem; macOS reported 54
clones and no fallbacks. Switching from a default-copy seed to explicit-clone
replay retained all three hits. Mutation isolation, exact output parity and
corruption rejection passed. The public Bazel sync/build/test check and all 53
existing project-sync tests passed on macOS. No Linux COW speedup or upstream
performance claim follows from the fallback check.

## Project run and test targets

Graph sync accepts multiple entry projects and records each framework's runtime
output location. Select projects without spelling SDK output paths:

```starlark
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary", "msbuild_graph_test")
load(":graph.generated.bzl", "app_graph")

app_graph(name = "graph")
msbuild_graph_binary(name = "app", graph = ":graph", project = "App/App.csproj")
msbuild_graph_test(name = "tests", graph = ":graph", project = "Tests/Tests.csproj")
```

Use `framework = "net10.0"` when a project has multiple generated frameworks.
Run targets require executable projects. Test targets support executable, MTP
and VSTest protocols through the shared test launcher. A selection action copies only the selected project's
runtime output directory. Test runfiles exclude graph sources, intermediate
outputs and the timing report. The selection action reruns when the graph changes,
but unchanged runtime bytes preserve the Bazel test cache entry.

`python3 tests/graph_build/bazel.py --sync` passed on macOS ARM64 with Bazel
9.2.0 and SDK 10.0.400: persistent sync/check, two entry projects, executable
run, unrelated edit retaining a cached test, and dependency body edit failing
the test. Selected runtime files are materialized, not sandbox symlinks.


## Graph configuration and locked packages

Set `configuration` (default `Release`) and optional `framework` on
`msbuild_sync(mode = "graph")`. These selections persist for sync and check;
the generated contract applies them to Restore and compilation. Multiple entry
projects share the graph; Restore currently visits each entry sequentially.

Pass the existing `msbuild_package_lock` as `package_lock` on sync. Package
providers retain their original archive closure, which the generated graph
consumes with the extraction outputs that verify the configured hashes. Restore
uses only those archives. Exact direct package versions must occur in the lock;
transitive packages must also be present for offline Restore to succeed.
Generated contracts pin the package archive digests, rejecting package changes
before Restore until sync runs again.

By default sync does not run Restore and rejects package build/content assets.
The explicit `package_build` opt-in below transfers their evaluation effects. Existing richer mappings use the project
backend. Package graphs retain conservative dependency invalidation; optimized
reference boundaries remain limited to the qualified package-free case.

The [graph quickstart](../examples/graph-quickstart/README.md) shows the complete
app-developer workflow. Focused commands, using the pinned wrapper overrides:

```sh
python3 tests/graph_build/devex.py
python3 tests/graph_build/quickstart.py
```

On macOS ARM64, SDK 10.0.400 and Bazel 9.2.0, these passed: locked transitive
managed packages, package upgrade, Debug/framework selection, stale package-set
rejection, missing closure rejection, unsupported package-build asset rejection,
archive-hash enforcement, and committed-example sync/check/run/test. The
committed example also passes on Bazel 8.8.0. Existing 53 project-sync controls and
generated body/API/publish invalidation controls also pass. These checks do not
establish Linux, MTP/VSTest, package build-task or remote execution parity for the
new developer workflow.


## Package build assets and test protocols

Declare `package_build = True` on graph-mode `msbuild_sync` to run offline Restore
in a disposable, materialized copy of the workspace. This executes Restore
targets from the trusted, pinned packages. It never restores into the checkout.
Sync evaluates the resulting NuGet imports, including package props, targets and
content items. The ordinary graph build still restores offline from the same
pinned archives; changing the package set requires sync before building.
Both paths clear ambient feeds/fallbacks; the action rejects Restore-source
overrides in its contract.

Declare files read by package tasks with `package_inputs = ["shared/schema.json"]`
when SDK item evaluation cannot discover them. These become Bazel source inputs
and shared project fingerprints. Generated outputs must stay in declared output
or intermediate directories. This is an explicit input contract, not filesystem
tracing or a guarantee that arbitrary tasks are hermetic. Property-bound tool
closures and legacy per-project settings still require transfer.

Graph run/test targets now reuse the existing runtime and test launcher. MTP and
VSTest support result XML, filters, settings, declared data, retained outputs and
empty-selection rejection. The SDK decides the project's output type. No MSBuild
invocation occurs during test execution.

```sh
python3 tests/graph_build/devex.py
python3 tests/graph_build/protocols.py
```

On macOS ARM64 with SDK 10.0.400 and Bazel 9.2.0, the package fixture passes
restored props, generated C# source, copied content, declared task-input edits,
checkout-preservation and package pin checks. Real xUnit/MTP and xUnit/VSTest
fixtures pass success, failure, skip, filtering, empty-selection, retained output
and recovery controls on Bazel 8.8.0 and 9.2.0. The executable fixture retains its unrelated-edit test-cache check.
These are small graph fixtures. Broad upstream parity remains a default-switch gate.

### Stable Linux graph paths

Set `app_graph(linux_stable_paths = True)` (or the same attribute on
`msbuild_graph`) to run the graph beneath fixed `/__rules_msbuild_graph` paths.
The worker must provide `/usr/bin/bwrap`. Missing Linux support fails the action;
there is no fallback. Each action owns its writable output and scratch trees.

This is a path-stability boundary, not a hermetic system toolchain: `/usr`, loader
configuration, certificates and `/proc` remain read-only host inputs, and network
access remains available for the project-cache transport. Processes are not in a
separate PID namespace. The qualified Apple Container worker rejects mounting a
new `/proc`, so the namespace uses the existing read-only mount explicitly.
Do not share cache entries across incompatible worker system images.

Linux ARM64 qualification in `native-aot-declared`, SDK 10.0.400:

```sh
RULES_MSBUILD_DOTNET_ROOT="$SDK" \
RULES_MSBUILD_PROJECT_CACHE_URL="$PROJECT_CACHE_URL" \
python3 tests/graph_build/linux_paths.py
```

Four fresh output/scratch directories share only the HTTP project cache. Initial
build: 0 hits/3 misses; relocated consumer: 3/0; dependency body edit: 2/1;
API edit with transitive references: 0/3. Each executable prints the expected
value, including refreshed dependency implementations. This directly qualifies
the namespace launcher. `python3 tests/graph_build/bazel.py --sync
--linux-stable-paths` also passes on Bazel 9.2 with the container's processwrapper
sandbox, including unrelated-edit test-cache reuse and dependency invalidation.
The fixture uses batch mode because Apple Container does not promptly reap
Bazel server zombies. Native Linux sandbox nesting is not qualified.

The same `linux_paths.py --projects 128` test passes 0/128 seed hits/misses,
128/0 relocated replay, 127/1 body edit and 0/128 API edit. The last case retains
transitive compiler references. Runner totals were 65.75s, 8.55s, 10.11s and
65.44s respectively, including Restore and project-cache transfer; these are
single qualification runs, not paired raw-MSBuild benchmarks.

### Declared tasks and generated inputs

Graph-mode sync now accepts these existing mapping fields:

- `projectDefaults.properties`: graph-wide global properties, passed to both
  evaluation/build. Restore uses each project's authored framework set instead
  of forcing the entry framework onto tools and dependencies. Runner-owned paths and package sources
  cannot be overridden. Per-project property overrides remain unsupported.
- `documents`: reviewed SHA-256, target/task names and explicit task input paths.
- `inputItems`: additional file-bearing items; `evaluationItems`: reviewed
  bookkeeping items. MSBuild keeps their metadata and target behavior.

Use `msbuild_sync(inputs = {":task_dll": "tools/Task.dll"}, mappings = "sync.json",
mode = "graph", ...)` for a generated task assembly. List it and its dependency
files in the document's `inputs`. Sync emits `msbuild_graph.input_paths` and the
same logical paths in the input contract. Each label supplies one file.
Alternatively, pass existing `msbuild_file_binding` labels through `bindings`.
Sync and build compose the managed tool's project dependencies, package runtime
assets and data under `.graph-tools`. Property values remain workspace-relative
in the contract and bind to action paths at execution. Every closure file is
hashed. Changing a binding property or entry requires sync; implementation/data
edits do not. Native executable layouts can use the same bindings; legacy reference-role mappings remain unsupported.
Custom-task graphs retain conservative dependency invalidation. Task outputs
must stay in the declared intermediate/output directories or explicit `outputFiles`. These mappings
specify a reviewed closure; they do not discover arbitrary filesystem reads.

`python3 tests/graph_build/mappings.py` passes generated task assembly execution,
custom file items, task-input edits, graph-wide properties, stale-document
rejection and unsupported-setting rejection on macOS ARM64/Bazel 9.2.
`python3 tests/graph_build/web.py` passes Web/Razor compilation, replay and Razor
source-edit invalidation, including standard `AssemblyAttribute` items.

### Tool and SDK qualification

On macOS ARM64 with SDK 10.0.400 and Bazel 9.2:

```sh
python3 tests/graph_build/tools.py
python3 tests/graph_build/analyzers.py
python3 tests/graph_build/package_sdks.py
python3 tests/graph_build/sync.py
python3 tests/graph_build/signing.py
```

The tool fixture runs a task with a project dependency, NuGet dependency, layout
prefix and data file through public sync/build. Unchanged closures replay;
dependency-body and data edits invalidate the consumer. Binding changes require
resync. Source-built analyzers are graph outputs, including when stale DLLs
already exist. Their implementation changes invalidate consumers. SDK-owned
assembly references are allowed; arbitrary host assembly paths remain rejected.
Signing keys are declared even when they live outside a project directory; key
edits invalidate snapshots. Evaluation roots resolve filesystem aliases before
Restore to prevent duplicate projects racing to write the same generated imports.

Package SDKs listed in `global.json` resolve from declared archives before
Restore. The owned workspace temporarily uses a local-only NuGet config and
package root. The authored config is restored before evaluation/build; a
content-copy test checks that its original bytes reach the output. Unused SDK
registry entries are allowed; a missing used SDK fails even after a warm successful run. Package build mode also accepts SDK
implicit package versions only when the restored identity is in the exact lock.
Restore requires the package closure for all authored frameworks, even when the
build selects one framework. A mixed-framework synthetic covers that distinction.
These checks do not qualify arbitrary SDK resolver plugins or network isolation.

### Upstream migration qualification

The reviewed document mappings live in `tests/graph_build/upstream`. They are
contracts for the inspected snapshots, not general exceptions for those projects.

| Scope | Result / next gate |
| --- | --- |
| Orchard CMS Web at `04467a3438d4255627c1a478598a1585b3ff2947`, net10.0 | Generated contract builds all 202 projects from 9,546 project inputs and 347 declared package archives, including SourceGenerators and Razor modules. Requires the reviewed Orchard mapping and `RestoreUseStaticGraphEvaluation=false` (static-graph Restore fails in this snapshot). |
| Avalonia.Controls, net8.0 | Generated build passes with 105 declared archives and the signing key: 7 projects, 11 built configurations. Clean-output replay hits all 11; all 174 snapshot files match. This covers Controls and its dependencies, not the full Avalonia repository. |
| System.IO.Pipelines, net10.0 | Generated Build and same-path replay pass with 86 declared archives, 30 configured projects and 831 captured output files, including 108 shared binplace files. This is the bounded macOS ARM64 managed slice; native host, full runtime and cross-path replay remain open. |

Orchard sync command, with an input manifest mapping exact cached package
identities to archives and a disposable source checkout:

```sh
dotnet tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll \
  "$SOURCE" "$SDK/sdk/10.0.400" \
  src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj --graph --framework net10.0 \
  --package-build --inputs "$INPUTS" --runfiles "$RUNFILES" \
  --mappings "$REPO/tests/graph_build/upstream/orchard.json"
```

Stage the contract's shared/configured inputs and raw archives into an owned
workspace (`.package-source` for archives), then run `GraphBuild action`.
Use identical environment settings for seed and replay; the current fingerprint
includes evaluated environment properties.
`tests/graph_build/replay_outputs.py WORKSPACE CONTRACT CACHE REPORT` removes
only declared outputs (`--seed` also builds a seed with the same environment)
and compares a replay with every seeded snapshot output. MSBuild's local
`AssemblyReference.cache` files are excluded, matching the snapshot policy.
Orchard replay hit all 202 projects; all 16,250 snapshot files matched.
Its runner took 36.96s, including Restore, validation and hashing; this is
same-path local replay, not remote or relocated-cache evidence.
Shared package paths are now validated once per graph instead of per project.
In two Orchard cold qualification runs, evaluation/validation fell from 58.70s
to 5.14s; total runner time fell from 179.60s to 124.52s. These are single local
runs, with compilation essentially unchanged, not a paired raw-MSBuild benchmark.

Full migration parity still requires relocated replay, body/API edits and runtime
checks against raw graph-mode MSBuild on each upstream. Existing test-only plugin
measurements do not qualify these public generated contracts. Per-project rules
remain the default.

### Shared output directories

Graph mappings accept `outputFiles`, a list of required workspace-relative file
paths. MSBuild properties expand during sync, for example
`"outputFiles": ["shared/$(AssemblyName).dll"]`. Different configured projects
can own different files in one directory. Ownership overlaps, input overwrites,
preexisting outputs and missing produced files fail. Snapshots restore these
files and validate ownership; custom file outputs use conservative dependency
invalidation. This declares output ownership, not permission for undeclared reads.

`python3 tests/graph_build/output_files.py` passed on macOS ARM64 with SDK
10.0.400: two projects share an output directory, replay restores both files,
a body edit invalidates the dependent build, and conflict/missing-output controls
fail as expected. Runtime's binplace outputs still require reviewed declarations.

### Native generator bindings

Graph sync/build accept `msbuild_native_tool` through `msbuild_file_binding`.
The complete declared layout is staged once; its executable and data files
participate in cache identity, including executable permission bits.
`python3 tests/graph_build/native_tools.py` passed on macOS ARM64/Bazel 9.2:
a compiled C generator runs through public sync/build, replays, and rebuilds
when its executable or data changes. Removing execute permission fails instead
of returning an old cached success. The fixture explicitly uses `/bin/sh` and
the platform C runtime; this does not establish a portable native system closure.

### Runtime contract qualification

The System.IO.Pipelines slice now passes a generated graph build with 30
configured projects (32 graph nodes), offline packages and API validation.
Runtime exposed three input requirements: package-owned .NET Framework reference
assemblies, API suppression files read inside targets, and MSBuild task-host SDK
paths. The runner binds `DOTNET_HOST_PATH` and `NetCoreSdkRoot` to its declared SDK.
It does not disable task hosting or API checks. Package SDK casing aliases require
matching declared bytes; missing package-authored analyzer-config candidates are
ignored, while existing files still require ownership.

Mappings can use evaluated item lists in `outputFiles` and select contracts with
`frameworkOverrides`. Required outputs must exist after a build. Runtime's shared
binplace directories need individual file ownership, not ownership of the whole
directory. This qualification is a managed library slice, not a full runtime,
native host or SDK build.

Focused checks passed on macOS ARM64 with SDK 10.0.400:

```sh
python3 tests/graph_build/output_files.py
python3 tests/graph_build/tools.py --task-host
python3 tests/graph_build/package_sdks.py
python3 tests/graph_build/framework_references.py "$PACKAGES"
bash scripts/check-dotnet.sh
```

The Framework fixture needs the declared ReferenceAssemblies and net462 packages
at version 1.0.3. The out-of-process task check qualifies the graph rule; the
legacy rule's task-host launcher still fails this case.

Runtime output replay passed at revision `60629d14374c56f1cb51819049ad1fa529307f8d`: all 30
configured projects hit and all 831 captured files matched, including 108 shared
binplace files. Replay took 9.50 seconds including offline Restore and input
validation. The concurrent cold qualification took 114.77 seconds; these are
single local runs, not paired performance measurements. Reproduce the reviewed
macOS ARM64/net10.0 mapping with
`python3 tests/graph_build/upstream/runtime_contract.py "$MAPPING"`, then use the
package-build sync and `replay_outputs.py --seed` flow above. The output fixture
is specific to this revision, platform and entry point.

### Publish and layout providers

Generated `app_graph` accepts `target = "Publish"`. Run/test selectors use the
selected project's evaluated publish directory for these graphs. An output that
MSBuild did not publish fails extraction; library dependencies are not implicitly
published just because their entry point was published.

`msbuild_graph_layout(name = "published", graph = ":graph", project = "App/App.csproj")`
exports the selected project's complete output directory as `MSBuildLayoutInfo`.
It composes with `msbuild_layout` and `msbuild_runtime`, including source-built
runtime components. This provides the artifact connection; it does not qualify a
full source-built native runtime through the graph runner.

`python3 tests/graph_build/bazel.py --sync --publish` passes on macOS ARM64 with
Bazel 9.2: generated Publish, executable tests, edited-test invalidation, an
unrelated-project test-cache hit and composition of the published app layout.
`analyzers.py --project-reference` covers `OutputItemType="Analyzer"`;
`reference_roles.py` covers aliases, `Private=false`, constant changes and replay.
Special reference metadata currently uses conservative dependency invalidation.

### Linux migration gate

With the updated runner, `linux_paths.py --projects 32` passed in the local Apple
Linux ARM64 worker: a relocated consumer fetched all 32 projects from a separate
HTTP cache, a body edit rebuilt one, and an API edit rebuilt the chain. The public
stable-path graph action also runs on Bazel 8.8 and 9.2 with
`--spawn_strategy=processwrapper-sandbox`. These checks use fresh source/cache
locations, not shared local snapshots.

The Apple container cannot register Bazel's native `linux-sandbox` strategy.
Native sandbox nesting and the intended worker/sandbox combination therefore
remain unqualified; a Linux worker supporting that strategy is required. This
is not evidence for Bazel remote execution or a fully hermetic system closure.

The public Linux check exposed bootstrap-path-dependent runner bytes. The runner
build now maps repository and temporary intermediate paths to stable names.
`tests/graph_build/linux_bazel_remote.py` passes with three fresh projects: Bazel
8.8 seeds them, Bazel 9.2 replays all three from another output base, and a body
edit replays two and rebuilds one. Both bootstraps produce identical runner DLLs.

For this rule, supply cache settings with explicit values, for example
`--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=http://cache:8080`. The current
allowlist reads Bazel's fixed action environment; the inherited-name shorthand
`--action_env=RULES_MSBUILD_PROJECT_CACHE_URL` does not reach the action.

### Reviewed dependency roles

Graph mappings may explicitly enable reference boundaries after reviewing the
SDK, package targets and custom tasks:

```json
{
  "projectDefaults": { "referenceBoundary": true },
  "projects": {
    "App/App.csproj": {
      "implementationDependencies": ["Generator/Generator.csproj"]
    }
  }
}
```

Reviewed boundaries and implementation roles generate contract version 3 so older
runners reject them instead of silently ignoring dependency semantics. Existing
version 1/2 contracts remain readable.

`referenceBoundary` is optional. Omission retains conservative automatic
qualification; `false` disables reference reuse. `true` attests that ordinary
project dependencies are consumed through compiler references and declared
runtime copies. It requires standard managed outputs and rejects trimming,
ReadyToRun, Native AOT and single-file transforms. Targetless multi-targeting
nodes coordinate their configured builds and do not own assembly copies.
If multiple framework producers map to the same consumer copy, sync rejects the
reviewed boundary; use the conservative contract for that graph.

`implementationDependencies` names direct workspace-relative `ProjectReference`
paths whose implementation a task consumes. Analyzer references, non-reference
edges and explicit reference targets already use implementation fingerprints.
Custom tasks that read dependency IL, or an analyzer supplied through an ordinary
reference, must declare that role explicitly. These contracts do not trace task
reads or make arbitrary targets safe automatically.

Reference consumers hash reference assemblies plus dependency configuration and
noncompiler inputs. Noncompiler inputs remain transitive even when
`DisableTransitiveProjectReferences` is true: content can still propagate.
Files used both as source and content/analyzer data retain implementation hashes.
Consequently a dependency resource/configuration edit can rebuild consumers even
when its reference assembly is unchanged. Runtime DLL/PDB/XML copies are refreshed
from current producers, with exact byte checks when saving snapshots.

Run `python3 tests/graph_build/reviewed_dependencies.py` for package/custom-target
body and API edits, source-built analyzer edits, explicit implementation roles,
transitive content, dual-role sources and multi-targeting. The body and tool
controls compare all captured outputs with independent cold builds. Existing
`invalidation.py` and `replay.py` cover documentation copies, Publish and corrupt
snapshots. These are local correctness checks, not remote-cache measurements.

## Explicit graph Restore preparation

Generated graphs can opt into a separate Bazel Restore action:

```json
{
  "projectDefaults": {
    "preparedRestore": true,
    "restoreInputs": [],
    "restoreOutputs": []
  }
}
```

Run graph sync with these mappings, then use
`app_graph(name = "app", linux_stable_paths = True)`. The facade declares
`msbuild_graph_restore` and supplies its artifact to `msbuild_graph`. Every
configuration must opt in. The default still runs Restore inside the graph action.

The generator includes project files, imports, shared inputs and standard NuGet
outputs. Add any custom Restore inputs and outputs as workspace-relative paths.
Opting in asserts that these lists are complete: custom targets that inspect
source content, file existence or other files need those inputs declared too.
Body edits reuse preparation only when they do not affect this Restore contract.
Package, SDK, configuration, import and environment changes invalidate it.
The public rule requires stable Linux paths because NuGet outputs contain paths.

Preparation validates its input bytes and generated file set. Consumption checks
SDK identity, input bytes, payload bytes and recorded executable permissions,
rejects conflicts, then copies files into the action workspace. Bazel may
normalize tree-artifact modes; the runner restores the recorded modes. It does
not trust timestamps or borrow writable cache files. Final graph input
verification still runs.

`prepared_restore.py` and `prepared_restore_sync.py` cover reuse and rejection.
`linux_prepared_restore.py --generated` checks the generated public rules under
native Linux sandboxing: a body edit executes no Restore action; a props edit
executes one. These are small-fixture results. The initial full Orchard probe
was slower and exposed an empty-directory discovery difference; see the
[execution plan](graph-cache-plan.md). This is not yet an Orchard performance
recommendation or a replacement for incomplete custom Restore contracts.

### Directory existence inputs

For targets that depend on an empty directory's existence, graph mappings accept
`"inputDirectories": ["Web/wwwroot"]`. Paths are workspace-relative and must
exist during sync. The generated version-4 contract records their presence;
fresh actions recreate them before Restore/evaluation. Files beneath them still
need normal explicit declarations. This is not a recursive directory input or
a request to copy arbitrary contents.

Directory declarations affect cache identity. Files, symlinks, reserved package
and tool paths, and overlap with declared output trees are rejected. Final
verification rejects target deletion of a declared directory. The Web SDK
fixture `tests/graph_build/input_directories.py` compares static-asset discovery
with raw MSBuild and fresh snapshot replay, including an empty `wwwroot`.
Absent-directory conditions and arbitrary directory enumeration are not inferred;
custom targets still need reviewed contracts.
