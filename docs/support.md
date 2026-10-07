# Support and limits

The graph workflow is the sole backend. Pins: SDK **10.0.400**, Bazel
**8.8.0 / 9.2.0**. Inputs, packages, tool layouts, generated files and output
ownership must be explicit. Sync does not trace arbitrary task reads or acquire
missing packages.

## Qualified SDKs

These native suites passed on Linux ARM64 with both Bazel pins. They check public
sync, raw MSBuild parity, edits, failures and cached/uncached workers.

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

`bash scripts/bazel.sh test //tests/integration:source_globs --test_output=errors`
passed on Linux ARM64 with both pins: method-body output changes, addition/removal/
rename guards and resync followed by app/tests. Sync controls cover exclusions,
hidden files, symlinks and framework-specific inputs. See [sync](api.md#sync).

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
passed both pins, including multi-target selection, implementation references,
package basename collisions and transitive copy refresh. Twenty sync controls reject
conflicting selections, undeclared consumer inputs, input mutation and unsafe outputs.

Normal Bazel remote-cache recovery hits both Restore and graph actions on a fresh
consumer. Forced project recovery with a stopped producer also passed: complete
inventories yielded **481 hits / zero compilations**, with all **9,972 retained
files** matching bytes/modes. Traversal, NoTargets, Worker, IL and Arcade fixtures
passed independent HTTP recovery on both pins with Bazel action caches disabled.
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

- Persistent workers require Bubblewrap and nested namespaces. Worker/remote evidence
  is Linux ARM64; Linux x86-64, macOS workers and RBE are unqualified.
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
