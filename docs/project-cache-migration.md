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

1. Generate graph contracts from project sync, including declared task/tool
   bindings and dependency-copy roles. `ProjectSync --graph` now generates
   package-free SDK graph contracts and Bazel declarations. Rich mappings and
   optimized reference boundaries still need transfer; upstream probes still
   use repository-specific discovery.
2. Extend configuration and restore qualification to upstream graphs. Version 2
   contracts now select per-configuration inputs, outputs, reference boundaries,
   and dependency-copy bindings using explicit global-property selectors. Missing
   or ambiguous matches fail. Offline restore uses evaluated assets and extensions
   paths; a multi-targeted synthetic with a custom extensions directory passes.
3. Qualify package-rich generation, MTP/VSTest execution and results, native tools,
   and the existing source-built-runtime/publish interfaces through the generic
   rule. Acceptance now includes offline package assemblies, `buildTransitive`
   source generation and package upgrades, alongside package-free build/publish
   and executable tests. Rich test protocols, native tools and runtime providers
   remain open.
4. Provide stable workspace and SDK paths inside Bazel execution. The two-worker
   test uses matching container paths; ordinary Bazel sandbox paths are not stable
   enough for project-cache hits under the current conservative identity.
5. Run Orchard, Avalonia, and the supported runtime slices through the generic
   rules and compare complete body/API/resource/test/publish workflows with warm
   raw graph-mode MSBuild and the existing rules, including restore and transfers.

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
3/0 hits/misses, body edit 2/1, API edit 1/2, resource edit 2/1, publish seed
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

For a package-free `Microsoft.NET.Sdk` graph, keep the existing `msbuild_sync`
target and run:

```sh
bazel run //:sync -- --graph
bazel run //:sync -- --graph --check
```

Sync writes `graph.generated.json` and `graph.generated.bzl`. Add this to the
root BUILD file:

```starlark
load(":graph.generated.bzl", "app_graph")

app_graph(name = "app")
```

The generated contract declares evaluated source files, imports, configuration
selectors and output directories. Its dependency invalidation is conservative;
reference-boundary optimization and dependency-copy rebinding are not inferred.
Sync rejects package references, tests, custom targets/tasks, external assembly
references, custom item kinds and existing mapping/tool/package inputs until
those contracts are transferred. Run sync for the intended SDK/platform; this
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
package-aware sync, Linux Bazel stable paths, large package-rich graphs, native
tasks and MTP/VSTest integration are still unqualified.
