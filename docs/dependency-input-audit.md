# Dependency input audit

Bazel owns inter-project scheduling and caching; MSBuild retains project SDK and
NuGet behavior. This audit follows each input to its consumer before narrowing it.

## Compilation inputs and consumers

| Input | Consumer / reason | Decision |
| --- | --- | --- |
| Project, sources, imports, item files | Project evaluation, SDK targets, compiler and generators | Keep declared files and metadata |
| Compiler reference assemblies | ResolveAssemblyReferences and Csc; friend/implementation reference mode is explicit | Keep configured direct/transitive semantics |
| Runtime-only reference metadata for executable/test projects | ProjectRestore.Inject and SDK dependency manifest generation | Keep; not runtime implementation DLLs |
| Transitive restore-project JSON | ProjectRestore.Inject reconstructs NuGet graph identities, package requests and private edges | Keep even for direct-only compilation |
| NuGet package trees | Restore, package references, imported targets, analyzers and runtime export | Keep whole declared trees until asset-level separation preserves all consumers |
| Project analyzer implementations, helpers and packages | ProjectAnalyzers prepares executable analyzer load groups | Keep implementation closure, not just reference assemblies |
| Task implementations, helpers, packages and data | BuildTools and file bindings execute task code | Keep complete declared tool closure |
| Explicit project outputs, layouts and target-result items | SDK/custom targets consume these declared inputs | Keep the selected artifact role |
| Assembly selection identities | AssemblyContracts validates configured branch convergence | Keep small identity records |
| SDK and runner | MSBuild evaluation, restore, compilation and SDK tasks | Keep for compilation |
| Ordinary dependency runtime trees and runtime data | ApplicationLaunch and test execution | Already excluded from ordinary compilation; preserve in runfiles |

The implementation is in `msbuild/private/project.bzl`, `inputs.bzl`,
`selection.bzl` and `tools/ExplicitBuild`. Existing providers already separate
reference, runtime, tool and restore roles. No change to transitive reference
semantics is justified by this audit.

## Inputs to remove

- Assembly pairing reads reference/identity/restore files using the runner. It
  does not execute MSBuild and needs the runner runtime, not SDK compiler assets.
- Application/test launchers compose runtime files and execute the declared host.
  They need the runner runtime plus that host, not the complete build SDK. The
  legacy fallback host must retain all installed shared frameworks, including
  ASP.NET Core. Separately declared platform runtime closure files must remain.

## Validation

The [recorded evidence](dependency-input-evidence.json) covers Linux ARM64,
SDK 10.0.400, and Bazel 8.8.0 / 9.2.0. Both Bazel versions pass 43 analysis tests
and the eight scenarios below. Runtime/tool/analyzer and test protocol suites
ran on 9.2.0. Repository style, warning and unit checks passed (101 unit tests).
Full SDK retention for compilation and whole NuGet package trees are deliberate
limits, not claims that every file in those trees is necessary.


| Scenario | Compilations executed | Test executed |
| --- | --- | --- |
| Baseline | Leaf, middle, app | Yes |
| No-op | None | No |
| Leaf body edit | Leaf | Yes; observed changed return value |
| Leaf API addition | Leaf, middle, app | Yes |
| Runtime-data edit | None | Yes; observed changed file contents |
| SDK-only file edit | Leaf, middle, app | No; output bytes unchanged |
| Fresh output base and empty cache | Leaf, middle, app | Yes |
| Another output base, seeded disk cache | None (three explicit cache hits) | No |

The body edit retains the compiler process and reference hashes. The API case
retains middle's reference bytes but app still consumes the leaf reference through
the SDK's normal transitive closure. Fresh execution uses a different compiler
process and matches every reference and runtime payload hash. The app loads a real
ASP.NET Core framework assembly with SDK and reference-pack files absent from its
runfiles. These are correctness/invalidation observations, not timing benchmarks.

Additional controls passed: 41 runtime/paired-contract cases (including friend
access, type forwarding, runtime-only changes and relocated cache recovery),
12 task-binding cases (helper body edits with unchanged references and deleted
producer recovery), 13 analyzer cases (helper edits, AdditionalFiles and stale
load-group rejection), seven MTP cases and 12 VSTest cases across xUnit, NUnit
and MSTest. Expected compilation/test failures are asserted negative controls.

The installed SDK inventory contains 4,907 files / 671,718,586 bytes. Its shared
application runtime subset contains 335 files / 118,708,269 bytes; the runner's
CoreCLR subset contains 191 files / 88,697,475 bytes. These inventory sizes exclude
our runner, application payloads and separately declared platform closure files;
they do not measure bytes actually transferred from a cache.

### Reproduce

Use a disposable Linux container with an init process, the pinned SDK, and the
repository's Bazel wrapper. `dependency_inputs.py` temporarily adds an SDK marker;
do not run it concurrently with other builds sharing that SDK.

```sh
bash scripts/dotnet.sh build tools/ExplicitBuild/ExplicitBuild.csproj -c Release
bash scripts/bazel.sh test //tests/analysis:all
USE_BAZEL_VERSION=8.8.0 bash scripts/bazel.sh --output_base=/tmp/analysis8 test //tests/analysis:all
python3 tests/explicit_msbuild/dependency_inputs.py /tmp/inputs9
USE_BAZEL_VERSION=8.8.0 python3 tests/explicit_msbuild/dependency_inputs.py /tmp/inputs8
python3 tests/explicit_msbuild/runtime_primitives.py /tmp/runtime-inputs
python3 tests/explicit_msbuild/tool_bindings.py /tmp/task-inputs
python3 tests/explicit_msbuild/protocol.py /tmp/test-inputs
python3 tests/explicit_msbuild/vstest.py /tmp/test-inputs
bash scripts/check.sh
bash scripts/check-dotnet.sh
```

For the analyzer suite, create an empty `src` workspace with the same MODULE and
registered local toolchain as the dependency-input fixture, set
`RULES_MSBUILD_REPOSITORY_CACHE`, then run
`python3 tests/explicit_msbuild/project_analyzers.py /tmp/analyzer-inputs`.

The new cold/replay comparison uses the same source location and separate output
bases with disk caching. It does not establish a new remote execution or HTTP
cache qualification, nor complete Orchard compatibility. No GitHub CI was
dispatched.
