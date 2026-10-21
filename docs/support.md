# Support and limits

The graph workflow is the sole backend. Pins: SDK **10.0.400**, Bazel
**8.8.0 / 9.3.0**. Inputs, packages, tool layouts, generated files and output
ownership must be explicit. Sync does not trace arbitrary task reads or acquire
missing packages.

The 9.3 upgrade passed 29 analysis/integration checks on Linux ARM64, including
8.8 compatibility, SDK facts, cached/uncached workers, compiler selections and
recursive-source HTTP Restore/project recovery. Cached HTTPS SDK acquisition also
passed with all downloader URLs blocked and metadata removed. Reproduce with:

```sh
SDK_VERSION_CACHE_URL=http://cache:8080 DYNAMIC_SOURCE_CACHE_URL=http://cache:8080 \
  bash scripts/bazel.sh test \
  //tests/analysis/... \
  //tests/integration:{sdk_versions,quickstart,sdk_locks,workers,recursive_sources,resolved_inputs} \
  --test_output=errors
```

The earlier 481-compilation runtime baseline and source-built SDK consumers below
retain their recorded 9.2 qualification. The downloaded-SDK runtime slice below
has separate 9.3 results.

## Downloaded SDK platforms

Downloaded-SDK controls passed on native Linux ARM64 and Linux x64 **under
Apple Rosetta**: 29 analysis/integration checks across both current Bazel pins,
plus 21 SDK/runtime repository controls. Scope: SDK selection/locks, quickstart,
SDK-only Web/Razor Build/test/Publish and HTTP recovery, cached/uncached sandboxed
workers, body/API edits and raw MSBuild output parity. The Web fixture checks the
actual process architecture; fixture declarations select the host SDK RID.

```sh
SDK_WEB_CACHE_URL=http://cache:8080 bash scripts/bazel.sh test \
  //tests/analysis/... \
  //tests/integration:{quickstart,sdk_locks,sdk_policies,sdk_web,workers} \
  --test_output=errors
python3 -m unittest discover -s tests/sdk_repository -v
```

The x64 controls used amd64 SDK/Bazel binaries in Ubuntu containers on an ARM64
Mac. This establishes emulated x64 behavior, not native x64 performance or
source-built SDK/runtime qualification. Native Linux x64 remains unqualified.

Native macOS ARM64 passed `//tests/integration:{quickstart,native_sdk}` on
both current Bazel pins with SDK **10.0.400**: the public catalog's packages,
Razor/Publish, app/tests, body/API reference checks, sync/check and an independent
strict-lock source/output-base consumer. These four controls also passed on
native Linux ARM64. All 24 SDK/runtime repository controls
also passed on macOS / 9.3. The portable `native_sdk` suite is ready for native
Linux x64; no host was available, so that platform remains unqualified. These
macOS controls use ordinary sandboxed actions, with remote actions disabled;
Linux workers, published-byte parity and HTTP recovery retain their separate
qualification above.

## Qualified SDKs

The SDK suites below were qualified on Linux ARM64 with Bazel 8.8.0 / 9.2.0:
public sync, raw MSBuild parity, edits, failures and cached/uncached workers.

| SDK / project | Qualified behavior | Native suite (`//tests/integration:`) |
| --- | --- | --- |
| .NET | Managed graphs, Build/Publish, app/test layouts | `quickstart`, `workers` |
| Traversal 4.1.82 | Nested coordinators, conditional/wildcard references, multi-target children, Pack/Publish | `traversal` |
| NoTargets 3.7.0 | `.proj`/`.csproj` file producers, nested Traversal, explicit products and downstream invalidation | `notargets` |
| Worker + Hosting 10.0.11 | Worker template, Build/Publish and bounded execution | `worker_sdk` |
| IL 10.0.0-rtm.25509.106 | `.ilproj`, managed consumers, deterministic DLL/PDB, Build/Publish | `il_sdk` |
| Arcade 10.0.0-beta.25509.106 | SDK composition, versioning, Build/Pack/Publish and generated packages | `arcade_sdk` |

Web/Razor [graph controls](../tests/graph_build/web.py) cover compile/replay, Razor
edits and assembly attributes; source-built Razor consumers are covered below.

`//tests/integration:sdk_web` passed both current Bazel pins on Linux ARM64 with
SDK **10.0.400**, using its bundled ASP.NET framework without `runtime_host`.
Build/test and Publish serve a compiled Razor page and published static assets;
content edits require no sync. Published files match ordinary/graph MSBuild bytes,
except SDK `Last-Modified` values in the static endpoint manifest (only those values
are normalized for comparison). Fresh-source/output-base action and forced project
recovery preserve all published bytes exactly and execute the edited web app;
project recovery yields three hits / zero compilations. This is a small web fixture,
not general Blazor/workload or real-project Publish qualification.

The [package-backed catalog](../examples/catalog-web/README.md) qualifies five
projects with Newtonsoft.Json / Humanizer, embedded data, Razor and static assets.
`SDK_WEB_CACHE_URL=http://cache:8080 bash scripts/bazel.sh test
//tests/integration:catalog_web --test_output=errors` passed both pins on native
Linux ARM64: ordinary/graph MSBuild Publish parity (same timestamp exception),
body/API edits and test invalidation. The body edit retained reference bytes with
four project hits / one compilation; the API edit yielded one hit / four
compilations. Bazel recovered both Restore and graph actions remotely; forced
HTTP project recovery (five hits / zero compilations) preserved every published byte and ran the app.
The public example uses the regular graph workflow; the fixture separately enables
Linux prepared Restore/workers. Evaluation reuse is off: Razor API changes can
trigger SDK reevaluation, which the retained-evaluation guard rejects.

`bash scripts/bazel.sh test //tests/integration:sdk_locks --test_output=errors`
passed 8.8.0 / 9.3.0 on Linux ARM64: automatic metadata resolution, native lockfile
facts, platform expansion, fresh-base recovery without metadata, extension-change
reuse, stale-pin rejection, archive hash/layout guards and private archives. Cross-version recovery
also passed after recording each Bazel version's registry entries. SDK **10.0.302**
(absent from the former catalog) passed sync/app/tests and a fresh clone in strict
lockfile mode with metadata removed; **10.0.400** retains quickstart coverage.

`//tests/integration:sdk_versions` passed **8.0.425**, **9.0.318** and
**11.0.100-rc.1.26425.128** on both Bazel pins: SDK-derived adapter frameworks,
sync/check, app/tests, body/API edits and fresh-base recovery without metadata.
Each SDK recovered the whole graph action through Bazel's remote cache; forced
HTTP project recovery returned three hits / zero compilations and identical outputs.
There is no SDK-family allowlist; see [adapter requirements](api.md#sdks).

`//tests/integration:sdk_policies` passed both Bazel pins on Linux ARM64: patch
fallback, latest patch/feature selection, prerelease ordering/filtering, locked reuse
after metadata changes, platform expansion, old-lock migration without metadata,
strict fresh-base recovery, invalid-fact rejection and explicit refresh. A real
`9.0.300` / `latestPatch` request selected **9.0.318** and passed sync/check/app/tests.
The declared `@dotnet//:update` target passed consecutive refreshes, preservation of
unrelated pins/hashes, metadata-failure recovery, strict lock reuse and optional
sync on both Bazel pins. The combined `--nuget-update` sequence also passed both
pins with SDK 9.0.318: stale native locks failed offline, package changes resolved
before sync, and failed package resolution preserved locks and the graph.
All 24 SDK/runtime repository controls passed on native
macOS ARM64 / 9.3. Other roll-forward policies
remain unsupported; selection uses published releases, not installed SDKs.

`//tests/integration:source_globs` passed both pins on native macOS ARM64 and
Linux ARM64: local/external-module graph compilation, body edits, pinned membership
and rejection of undeclared cross-repository sources.

`//tests/integration:evaluation_worker` passed both current pins on Linux ARM64:
reviewed body/API reuse, fresh build state, evaluation-input/task changes and failed-
build recovery. Retention requires explicit compiler-only input review; see
[configuration](api.md#caching-and-workers) and [runtime timings](performance.md#reviewed-evaluation-reuse).

## Downloaded SDK and runtime sources

The public `dotnet.sdk(version="10.0.400")` → native package update/check → offline
sync/check workflow passed on runtime v10.0.0, Linux ARM64 / Bazel 9.3.0. It retains
upstream SDK compiler behavior, including out-of-process `Runtime="NET"` tasks.

| Slice | Configurations / compilations | Archives / native locks | Compiled files matched |
| --- | ---: | ---: | ---: |
| Four managed roots | 182 / 163 | 106 / 91 | 1,447 |
| 39 roots / eight suites | 543 / 481 | 141 / 265 | 3,622 |

Both slices passed paired body/API parity, actual compiler-workset controls and
independent stopped-producer recovery: normal Restore + graph action hits, then
forced HTTP project recovery with zero compilations and identical bytes/modes.
The small slice's app verified and exercised the source-built Pipelines DLL on the
downloaded host. The large slice executed an app on its declared source-built native
runtime plus eight upstream suites. A healthy independent consumer now actually
executes all nine tests after normal Restore/graph action recovery and after forced
**481 HTTP project hits / zero compilations**. Both match **10,780 retained files**
including modes, **118,952 passed / 64 skipped** upstream cases, and loaded source-runtime
hashes. Test-result caching is disabled and the producer is stopped. See [measurements and reproduction](performance.md#large-downloaded-sdk-graph).
This is a bounded managed graph with declared native producers, not the entire
runtime repo, a full source-built SDK, Linux x64 or remote execution.

## NuGet inventories

`//tests/integration:solutions` passed `.sln` / `.slnx` update, strict child locks,
offline sync/test, native graph DLL parity, configuration mappings, exclusions,
solution dependencies and stale-file rejection on **8.8.0 / 9.3.0**, Linux ARM64.
`solutions_remote` fresh consumers recovered four projects with zero compilation,
identical product bytes/modes and successful execution for both formats/pins.
Single solutions without custom solution hooks are qualified; see [API](api.md#sync).

`//tests/integration:nuget_update` passed **8.8.0 / 9.3.0** on native Linux ARM64:
explicit update/check, offline native locks, app/Razor/Publish and rejection of
corrupt native hashes or malformed manifests. Failed resolution preserved locks
and contracts. The public update command also passed on macOS ARM64 / 9.3.

`//tests/integration:nuget_graph` passed both pins on Linux ARM64: central versions,
transitive Options dependencies, netstandard2.1/net10.0 with different Newtonsoft
versions, a packaged CA1822 failure control and an independent strict-lock consumer
with downloads disabled. Restore validation also skips inner-framework functions
inside false item groups, using MSBuild's native `ProjectInstance` evaluator;
incomplete Restore and missing SDKs still preserve locks/contracts. The graph action
recovered through HTTP. Root analyzer
settings are declared inputs; config-only edits enable/disable CA1822 without sync
and reject stale compilation. Automatic SDK discovery stops
at the declared workspace; nested/global configs are retained and authored outside
reads still fail validation (31 sync controls). The package-backed
catalog now uses generated inventories; its raw Publish/edit/recovery controls above
retain the same scope. Native macOS passed its app/Razor/Publish tests and checked a
9.3-generated contract unchanged with 8.8.

`//tests/integration:nuget_hierarchy` passed both pins on Linux ARM64: native
config inheritance/clears, disabled sources, nested source mappings, config-only
attestation, offline sync/test and rejection of outside configs. Traversal/NoTargets
HTTP action recovery also passed with native config discovery enabled. The hierarchy
control also passed on native macOS ARM64 / 9.3.

`//tests/integration:nuget_configured` passed both pins on Linux ARM64: shared
graph/entry properties, all-framework native locks, escaped property values,
offline sync/test and rejection of conflicting shared-project locks or reserved
Restore overrides.

`//tests/integration:nuget_shared_projects` passed both pins on Linux ARM64:
project-specific locks in shared directories, selected-SDK binding, strict dependency
drift rejection and atomic rejection of colliding lock names.

`//tests/integration:nuget_sdks` passed both pins on Linux ARM64: generated
Traversal **4.1.82** / NoTargets **3.7.0 → 3.7.56** inventories, global/inline SDK
selection, locked child dependencies and SDK-version invalidation. Incomplete
Restore and missing SDKs preserved locks/contracts. An independent consumer with
downloads disabled recovered Restore and graph actions through HTTP and preserved
all published product bytes. Unused SDK declarations require no archive.

IL and Arcade fixtures now use generated inventories. Both pins passed native
update/check, offline sync, raw Build/Publish parity, edits and failure recovery;
Arcade also passed Pack/package-consumer parity. Independent HTTP consumers
recovered two projects with zero compilation, identical bytes/modes and successful
execution. Pins: IL **10.0.0-rtm.25509.106** (including ILAsm/ILDasm), Arcade
**10.0.0-beta.25509.106**. Suites: `il_sdk`, `arcade_sdk` and their `*_remote` controls.

Reproduce with `SDK_WEB_CACHE_URL=http://cache:8080 bash scripts/bazel.sh test
//tests/integration:{nuget_update,nuget_graph,nuget_sdks,native_sdk,catalog_web,sdk_policies} --test_output=errors`.
Scope: SDK **10.0.400**, public NuGet.org V3 and standard project lockfiles;
[API](api.md#nuget-updates) lists update limits. No new x64 or source-built qualification.

## Downloaded runtimes

SDK **9.0.318** compiled a net9.0 app that ran on runtime **9.0.20**, rejected
**8.0.31 / 10.0.12** by default, and ran/tested on **10.0.12** with the app's
`RollForward=Major`. Metadata controls cover apphost exclusion, native facts,
platform expansion, metadata-free recovery, extension changes, stale pins, corrupt
hashes/archives and private layouts. Fresh-base recovery hit the graph action in
Bazel's remote cache with byte-identical outputs; 9.3 also acquired cached runtime
archives with all downloader URLs blocked.

The ASP.NET distribution also passed a bounded HTTP app/test compiled by SDK
**9.0.318**, running on **9.0.20**, and on **10.0.12** with `RollForward=Major`.
CoreCLR-only and default cross-major hosts were rejected. Metadata selection excludes
composite runtimes and targeting packs; incomplete ASP.NET layouts fail.
A separate source directory/output base recovered the whole graph action, then
ran the web app. Forced project recovery returned three hits / zero compilations
and byte-identical outputs. Metadata-free cached acquisition passed with downloader
URLs blocked on 9.3.

The following 25 analysis/integration checks and 17 SDK/runtime repository controls
passed on Linux ARM64. Integration suites cover both **8.8.0 / 9.3.0**:

```sh
RUNTIME_CACHE_URL=http://cache:8080 \
  bash scripts/bazel.sh test //tests/analysis/... \
  //tests/integration:{aspnet_runtimes,runtime_locks,sdk_locks,quickstart} \
  --test_output=errors
python3 -m unittest discover -s tests/sdk_repository -v
```

Scope: small managed fixtures, fresh output bases on one host; no new workload,
worker, additional-platform or source-built qualification. Other shared frameworks
need a complete declared layout. See
[runtime configuration](api.md#runtimes).

## Graph inputs

`//tests/integration:preparation` passed on Linux ARM64 / Bazel 8.8.0 and 9.3.0:
multi-root sync shares one offline Restore process and shared dependency walks,
retains authored root Restore hooks, builds both apps and preserves contracts on
failure. Sync controls also cover escaped/per-root properties, locked-mode isolation
and all-framework Restore. Compiler qualification retains the full private SDK
Build with up to four nodes, bounded by available CPUs. Serial/parallel controls
cover multi-targeting, implementation/reference assembly selection, XML copies and
byte-identical declarations; see [measurements](performance.md#parallel-compiler-qualification).

`//tests/integration:cached_sync` covers declared-source preparation, cached checks,
source/membership/producer/props/mapping invalidation, SDK-selected implementation
references, package inventories, runnable output and failure/publication guards.
The prepared contracts match ordinary sync. Pins: Linux ARM64, SDK 10.0.400,
Bazel 8.8.0 / 9.3.0. Directory producers materialize sandbox-projected files;
authored file/directory links remain rejected. Shell-task controls pass during
qualification and ordinary graph builds, with explicit SDK/system tool paths.
Independent four-project, runtime-bootstrap and 543-configuration managed consumers
passed strict-lock sync/check with fresh output bases and the producer stopped:
all recorded spawns were remote hits, with no qualification execution. See
[cached preparation](performance.md#cached-preparation); remote execution remains
unqualified.

The runtime preparation drivers now declare authored snapshots, native locks and
implicit analyzer configuration; SDKs and generated reference/targeting layouts
remain separate artifacts. A 32-configuration Pipelines slice matches ordinary
sync through body/API, props, mappings and lock-byte edits and original-state
remote recovery. The six-test JIT graph also matches ordinary sync: a live runtime
reference-assembly API edit requalifies, an unchanged check reuses preparation,
and restoring the producer recovers the original result and reference DLL bytes.
All six upstream tests execute successfully with test-result caching disabled.
Scope: Linux ARM64, SDK 10.0.400, Bazel 9.3.0.
Full managed preparation also matches retained ordinary declarations byte-for-byte.
Latest-payload independent recovery of the combined live runtime/JIT producer chain
remains unqualified: its final reseed was interrupted by exhausted host storage.
This does not affect the completed managed/bootstrap recovery or local JIT controls.

`bash scripts/bazel.sh test //tests/integration:source_globs --test_output=errors`
passed on Linux ARM64 with 8.8.0 / 9.2.0: method-body output changes, addition/removal/
rename guards and resync followed by app/tests. Sync controls cover exclusions,
hidden files, symlinks and framework-specific inputs. See [sync](api.md#sync).

`//tests/integration:dynamic_sources` and `:recursive_sources` passed 8.8.0 / 9.2.0:
flat/recursive Compile globs accept add/remove/rename/empty sets without sync or
another Restore action, with fresh sandbox output parity. Recursive globs cover new
subdirectories. Root patterns and ordinary `bazel-*` filenames inside source
directories also passed. Body edits reuse three evaluations with one project miss/two
hits; membership resets evaluation and retains conservative consumer keys. Guards
reject excluded/generated/package-crossing members, stale definitions and task-created
membership. Default unprepared actions also passed. With
`DYNAMIC_SOURCE_CACHE_URL=http://cache:8080`, 8.8.0 / 9.2.0 recovered Restore through
Bazel and all three projects through HTTP in a fresh output base, with identical app
outputs. Scope: a small managed fixture, one Linux ARM64 host; no large-graph or
independent-machine qualification for dynamic membership.

<a id="traversal-projects"></a>

Traversal coordinators keep Restore state without emitting assemblies. Sync rejects
dynamic skipping, per-reference target overrides and `TraversalPublishGlobalProperties`;
use conditional references and explicit graph properties. NoTargets requires reviewed
tasks and declared `outputFiles`; its fixture qualifies Build, not arbitrary side effects
or Pack/Publish pipelines.

IL requires locked native ILAsm/ILDasm packages; the fixture uses `IlasmFlags=-DET`.
Without a reference assembly, consumers hash its implementation. Arcade requires
its implicit packages and explicit version/repository inputs. Official/shipping builds
need `OfficialBuildId`; cold Pack uses a packable root with
`GeneratePackageOnBuild=false`. The fixture disables SourceLink/test-framework defaults;
ambient Git, Helix and full native Arcade orchestration are unqualified.

## Source toolchains and NativeAOT

Linux ARM64 consumer controls passed with the **10.0.100 source-built SDK**:
generated NuGet packages, NoTargets, Pack, Razor rendering and framework-dependent
Publish/run. Complete layouts include required SDK components: the qualified Razor
consumer adds StaticWebAssets from the produced component bundle.
The [component producer](../tests/source_sdk/component_graph_prepare.py) and
[pins](../tests/source_sdk/pin.json) are qualification tooling, not a general SDK
source-build rule. [Quick start](../examples/quickstart/README.md#source-built-sdk)
shows the public toolchain handoff. These consumers use Bazel 9.2.0.

Graph NativeAOT Build/Publish/run, body edits and missing-compiler rejection passed
on Linux ARM64. Independent recovery had one project hit, zero compilations,
identical ELF bytes and a fresh successful Bazel test. This qualifies downloaded
AOT packs and declared native tools, not a source-built AOT compiler or RBE.
Drivers: [SDK consumers](../tests/source_sdk/consumer_scenarios.py),
[NativeAOT](../tests/graph_build/native_aot.py) (`--help` lists inputs/phases).

## Runtime and cache evidence

The managed runtime fixture covers **260 project paths / 543 configurations /
481 compilations / 39 roots** on Linux ARM64 / Bazel 9.2.0. Earlier producer and
independent consumer runs passed **118,952 tests, 64 skips, zero failures** with
matching normalized outcomes. This is a selected graph, not the entire runtime repo.

Complete compiler inventories match raw compiler sets: LINQ body/API edits compile
**1 / 47** projects and match all **2,814 required DLL/PDB/resource files**. Generic
sync captures all **2,970** qualified project compiler selections without hand-authored
compiler/copy maps; its body/API and 481-hit local recovery checks preserve byte parity.
Native suites `resolved_inputs`, `resolved_package_copies` and `resolved_il_sdk`
passed 8.8.0 / 9.2.0, including multi-target selection, implementation references,
package basename collisions and transitive copy refresh. Twenty sync controls reject
conflicting selections, undeclared consumer inputs, input mutation and unsafe outputs.

Sync snapshots static implementation roles before the private SDK Build and
assigns analyzer roles only to actual direct graph edges. The native
`resolved_inputs` suite passes 8.8 / 9.3 on Linux ARM64: late bookkeeping adds no
edge, outer dispatch stays intact, and a generator body edit rebuilds both inner
consumers. Body/API, implementation and explicit tool controls retain fresh bytes.
Run `bash scripts/bazel.sh test //tests/integration:resolved_inputs --test_output=errors`.

The `restore_inputs` integration suite passes 8.8 / 9.3 on Linux ARM64: a
build-only producer API edit recompiles the consumer without Restore. `Exists()`
and globs retain layout, Restore outputs match conservative inputs byte-for-byte,
and fresh compilation matches. Ordinary `inputs` retains byte invalidation. Run
`bash scripts/bazel.sh test //tests/integration:restore_inputs --test_output=errors`.

Normal Bazel remote-cache recovery hits both Restore and graph actions on a fresh
consumer. Forced project recovery with a stopped producer also passed: complete
inventories yielded **481 hits / zero compilations**, with all **9,972 retained
files** matching bytes/modes. Traversal, NoTargets, Worker, IL and Arcade fixtures
passed independent HTTP recovery on 8.8.0 / 9.2.0 with Bazel action caches disabled.
Missing blobs rebuild; corruption fails. Warm local builds alone do not prove recovery.
See [performance and reproduction](performance.md).

### Unchanged JIT tests

Six authored runtime v10.0.0 tests pass on Linux ARM64, four CPUs / 6 GiB,
SDK **10.0.400**, Bazel **8.8.0 / 9.3.0**, running on source-built corerun:

| Project | Behavior |
| --- | --- |
| `CodeGenBringUpTests/Add1_ro` | Arithmetic |
| `CodeGenBringUpTests/Switch_ro` | Control flow |
| `CodeGenBringUpTests/FactorialRec_ro` | Recursion |
| `CodeGenBringUpTests/ArrayExc_ro` | Exception handling |
| `Generics/ConstrainedCall/vt1_cs_ro` | Constrained generic calls |
| `Directed/PREFIX/PrimitiveVT/callconv1_PREFIX_cs_ro` | Cross-assembly value-type calls through `helper.csproj` |

Bootstrap and test graphs use public NuGet update/check, sync/check and generated
`app_graph`. Reviewed mappings declare custom targets and deployment outputs;
sync captures the wrapper generator's implementation edges. All **36 DLL/PDBs**
and **69 deployed package files** match native raw bytes. All six raw binaries
also execute with the installed SDK absent. A body edit requires **eight hits / one
compilation**; a fresh generator edit requires **two hits / seven compilations**.
Success/failure codes **100 / 101** are preserved; omitted reference or helper producers fail.
Thirty-six sync controls cover tree bytes/membership, symlinks, collisions and
artifact-only outputs.

Helper body/API edits both produce **seven hits / two compilations** and refresh
the deployed helper. Public sync with `--compiler-references` qualifies the helper
and consumer bindings: upstream disables reference assembly emission, and Csc selects
`helper/helper.dll`. Its implementation bytes correctly invalidate the consumer.
Other custom test targets retain conservative boundaries. Restoring the authored files
recovers all nine projects and the exact original outputs.

A fresh relocated consumer, with the producer stopped and action/disk/test caches
disabled, recovered **nine HTTP project snapshots / zero compilations** and
actually executed all six tests. Compiled, deployed and runtime bytes/modes match.
The closed source-only input bundle is **27 MB**; SDK/packages come from declared
repositories. The ordinary SDK deployment project reruns when Bazel's action cache
is disabled and emits no assembly; its whole action remains cacheable by Bazel.

Reproduce with the pinned source archive/feed and declared source-runtime products:

```sh
python3 tests/graph_build/upstream/runtime_jit_public_prepare.py \
  SOURCE_ARCHIVE OUTPUT --source-products=SOURCE_PRODUCTS \
  --seed-report=PRODUCER_SEED --host-space-path=HOST_BIND \
  --cases=tests/graph_build/upstream/runtime_jit_cases.json --compiler-references
python3 tests/graph_build/upstream/runtime_jit_raw.py \
  SOURCE_ARCHIVE PINNED_FEED SOURCE_REFS RAW_RESULTS \
  --native-inventory=OUTPUT/workspace/nuget.lock.json \
  --cases=tests/graph_build/upstream/runtime_jit_cases.json
python3 tests/graph_build/upstream/runtime_jit_public.py OUTPUT/workspace RESULTS \
  --output-base=OUTPUT/bazel --raw=RAW_RESULTS/workspace --host-space-path=HOST_BIND
```

For independent recovery, run `runtime_jit_public_consumer.py OUTPUT RESULTS/seed.json
FRESH`, relocate it, stop the producer, then run the qualifier on `FRESH/workspace`
with `--seed-report=FRESH/seed.json`, a fresh `--output-base`, and the host-space bind.

Set `RULES_MSBUILD_PROJECT_CACHE_URL` to the HTTP cache. `PRODUCER_SEED` carries
the source-product archive hash. The owned root props resolve reference inputs
relative to the workspace, including private sync builds; authored test projects
stay unchanged. A fixture-only NuGet source mapping selects `dotnet-public` for
`Microsoft.Diagnostics.NETCore.Client`, avoiding differently signed copies from
racing feeds. Raw preparation uses native extraction of signed packages. Reports stay outside Git; these are correctness controls, not paired
performance measurements. Scope: these six tests and one helper dependency, not complete JIT
suites/stress, other architectures or RBE.

Inspect the authored SDK boundary with `runtime_jit_reference_probe.py RAW_RESULTS
SDK_ROOT REPORT.json`. It rebuilds the helper and consumer using the raw control's
properties, then checks reference-emission settings and `ReferencePathWithRefAssemblies`.

### Connected source-runtime workflow

Set `RULES_MSBUILD_PROJECT_CACHE_URL` to the HTTP cache. Prepare from the pinned
runtime source archive and declared native tools:

```sh
python3 tests/graph_build/upstream/runtime_checkout_prepare.py SOURCE_ARCHIVE PREPARATION \
  --toolchain=NATIVE_TOOLCHAIN_TAR --toolchain-sha256=TOOLCHAIN_SHA256 \
  --sandbox=BWRAP --sandbox-sha256=BWRAP_SHA256 --host-space-path=HOST_BIND
```

This runs public NuGet update/check and sync/check for the **543-configuration /
481-compilation** managed graph, generates five native producers, then syncs the
six-test JIT graph. Explicit framework mappings assign linker outputs to inner
nodes. A two-framework SDK control checks ownership against actual Build outputs.

Version inputs come from authored `eng/Versions.props`, native templates and the
pinned commit; components preserve those generated bytes. All five native archives
reproduce the qualified inputs byte-for-byte, including member order. Native
compiler/OS tools use a supplied, hashed bundle.

Preparation requires the qualified Linux ARM64 container with nested namespaces,
Python, download access and 12 GiB physical host headroom. `--resume` validates
input identities and skips completed stages. Immutable native archives are linked
within the owned preparation when possible. The fixture pins
`Microsoft.TestPlatform.ObjectModel` to `dotnet-public` to avoid signed-archive
ambiguity across upstream feeds.

No previous qualified workspace, compiled products archive or generated headers
are required. `OUTPUT` below means `PREPARATION/jit`. An existing producer can
still be connected with
`runtime_jit_public_prepare.py SOURCE_ARCHIVE OUTPUT --source-producer=WORKSPACE
--cases=tests/graph_build/upstream/runtime_jit_cases.json --compiler-references
--host-space-path=HOST_BIND`.

The generated test module binds `@jit_source_runtime//:references` into sync and
uses `@jit_source_runtime//:host` for execution. The producer's generated managed
graph, five native producers and package deployment form normal Bazel dependencies.
`bazel test //:jit_tests` builds/reuses that closure; there is no intermediate
`source-products.tar.gz` or hash-report handoff. Public update/check and sync/check
pass; compiled and host bytes/modes match the raw-qualified bounded control.

A fresh relocated Bazel 9.3 consumer, with the producer stopped, remotely recovered
Restore, managed graphs and all five native actions, then **actually executed all
six tests**. Forcing only the JIT graph action recovered **nine HTTP project
snapshots / zero compilations** and executed the tests again. Outputs, the
reference tree and runtime bytes/modes match the producer.

Reproduce with `runtime_jit_live.py OUTPUT RESULTS --output-base=OUTPUT/bazel
--bounded-seed=BOUNDED_RESULTS/seed.json --host-space-path=HOST_BIND`. Close inputs
with `runtime_jit_public_consumer.py OUTPUT RESULTS/seed.json FRESH`, relocate to
another machine, stop the producer, then run `runtime_jit_live.py FRESH RESULTS
--output-base=FRESH_BASE --seed-report=FRESH/seed.json --host-space-path=HOST_BIND`.

Connected edits rerun all six tests against the refreshed runtime:

| Edit | Runtime compilations | JIT compilations | Native actions | Restore actions |
| --- | ---: | ---: | ---: | ---: |
| Pipelines body | 6 | 0 | 0 | 0 |
| Pipelines API | 17 | 9 | 0 | 0 |
| Native version marker | 0 | 0 | 1 | 0 |

Body edits preserve reference and JIT output bytes. Native edits change only
`libSystem.Native.so`; managed outputs stay unchanged. Restoring each edit recovers
exact original bytes/modes with no graph, native or Restore executions. A fresh
machine recovered the **API-edited** closure through normal Bazel remote caching,
with the edited-state producer stopped: zero compilations/build/Restore executions
and six actual test runs. The 138 reference files use `build_inputs`: API edits
retain the JIT Restore action. All **2,908 Restore files** match the conservative
binding in bytes and modes. These are correctness controls, not paired timings.

```sh
python3 tests/graph_build/upstream/runtime_jit_connected_edits.py OUTPUT RESULTS \
  --output-base=OUTPUT/bazel --host-space-path=HOST_BIND \
  --case=api --close-api=EDITED_INPUTS
# Relocate EDITED_INPUTS, stop the producer; use a fresh output base:
python3 tests/graph_build/upstream/runtime_jit_connected_edits.py EDITED_INPUTS RECOVERY \
  --output-base=FRESH_BASE --host-space-path=HOST_BIND --recover=EDITED_INPUTS/seed.json
```

Omit `--case` to run body, API and native controls in sequence.

Fresh-source preparation passes in a clean container without prior runtime
workspaces or products, followed by six actual JIT test executions. The
managed and deployed JIT outputs match the raw-qualified control. This remains a
bounded runtime/test graph: no complete repository bootstrap, official versioning
or signing, native toolchain bootstrap, other-architecture or RBE qualification.
Reports are correctness evidence, not paired timings.

## Limits

- Persistent workers require Bubblewrap and nested namespaces. Native worker/remote
  evidence is Linux ARM64; x64 has the emulated controls above. Native Linux x64,
  macOS workers and RBE are unqualified.
- Unknown SDKs/workloads and whole-repository runtime/native build parity are unqualified.
- Custom task/analyzer/generator reads, package side effects and output ownership
  require contracts. Build compiler selections do not qualify Pack/Publish changes.
- Evaluation reuse is opt-in for reviewed compiler-only inputs. Arbitrary process,
  time or external reads cannot be safely retained. Verification still reads bytes.
- Sandboxing and graph isolation are distinct. Build trusted projects; exports reject
  links. HTTP publication has no atomic guarantee for divergent writers. Test sharding
  is unsupported.

Run suites with `bash scripts/bazel.sh test //tests/integration:SUITE
--test_output=errors`. Use fresh fixture/report directories and separate producer/
consumer containers for recovery. [Contributing](../CONTRIBUTING.md) covers tooling.
Keep reports outside Git. Earlier commands, pins and qualification details remain
in the [versioned record](https://github.com/keegan-caruso/msbuild-bazel/blob/fa2764b55f630ae0462e836aa3163b0807f07f7f/docs/support.md).
