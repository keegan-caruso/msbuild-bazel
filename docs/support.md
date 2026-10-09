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

Large runtime timings and source-built SDK consumers below retain their recorded
9.2 qualification; they were not rerun for this SDK change.

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
sync on both Bazel pins. All 24 SDK/runtime repository controls passed on native
macOS ARM64 / 9.3. Other roll-forward policies
remain unsupported; selection uses published releases, not installed SDKs.

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

Normal Bazel remote-cache recovery hits both Restore and graph actions on a fresh
consumer. Forced project recovery with a stopped producer also passed: complete
inventories yielded **481 hits / zero compilations**, with all **9,972 retained
files** matching bytes/modes. Traversal, NoTargets, Worker, IL and Arcade fixtures
passed independent HTTP recovery on 8.8.0 / 9.2.0 with Bazel action caches disabled.
Missing blobs rebuild; corruption fails. Warm local builds alone do not prove recovery.
See [performance and reproduction](performance.md).

One unchanged CoreCLR/JIT project,
`src/tests/JIT/CodeGenBringUpTests/Add1_ro.csproj` (#74), passed raw/graph byte parity,
body edits, source-built corerun execution and stopped-producer HTTP recovery
(three hits, zero compilations). Its dependency bootstrap and wrapper/compiler are
declared inputs; success exit code 100 is checked. This is one test, not a JIT suite.
Drivers: [prepare](../tests/graph_build/upstream/runtime_jit_prepare.py),
[qualify](../tests/graph_build/upstream/runtime_jit.py).

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
