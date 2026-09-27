# Building the SDK from source

This qualification targets .NET SDK 10.0.100 on Linux ARM64, starting from
`dotnet/dotnet` revision `b0f34d51fccc69fd334253924abd8d6853fad7aa`.
The qualification first built a complete SDK in one isolated Bazel action and
ran an app with it. The configured 22-component Bazel graph now also builds a
complete SDK on Linux ARM64. The default downloaded
SDK is unchanged; the produced SDK uses the existing
[SDK artifact contract](sdk-toolchains.md).

## Source and bootstrap inventory

[The pin](../tests/source_sdk/pin.json) records the source archive digest,
qualification container image, source-build configuration, bootstrap versions,
and hashes of the reviewed upstream build definitions. The source archive
contains 25 repository entries and 13 submodule entries. Its runtime revision
is the same `60629d14374c56f1cb51819049ad1fa529307f8d` used by our prior runtime
qualification; that selected slice is not a complete SDK runtime payload.

The upstream `global.json` requests SDK `10.0.100-rc.2.25502.107` and Arcade
`10.0.0-beta.25502.107`. Preparation also consumes previously source-built
artifacts `10.0.100-rc.2.25502.107`. Bootstrap inputs and final shipped outputs
must be audited separately. A source-built SDK still requires a bootstrap.

To inventory a pristine extracted source tree:

```sh
python3 tests/source_sdk/inventory.py /path/to/vmr /tmp/sdk-inventory.json
python3 -m unittest discover -s tests/source_sdk -v
```

The inventory rejects changed pinned definitions. Repository reference
conditions, metadata and shared update/remove operations remain verbatim. This
is a review inventory, **not an evaluated dependency graph**. MSBuild must
evaluate the selected configuration before producing Bazel dependency edges.
In particular, upstream flows generated package-version props and dependency
packages between repository builds; merely copying `RepositoryReference`
elements into Bazel would omit behavior.

## Qualification sequence

1. Pin sources, bootstrap inputs and native environment; inventory dependencies.
2. Establish the upstream source-only baseline and record payload and resource use.
3. Prove synthetic tool/package handoff, then one real source component.
4. Expand declared component/project producers while retaining upstream semantics.
5. Assemble the complete SDK and register it through `msbuild_sdk`.
6. Qualify console, project/package references, tests, publish, ASP.NET and Razor
   with the bootstrap SDK inaccessible to consumers.
7. Measure body/API edits and independent remote-cache recovery at another path.
8. Rebuild with the produced SDK; separately measure reproducibility.

The definition inventory, synthetic generated-package handoff, and real
NoTargets source-package handoff have passed. Acquisition of the pinned source
archive succeeded (about 460 MiB compressed, 3.3 GiB extracted). The full upstream
development-version baseline and produced-SDK consumer checks passed. The complete
Bazel component graph has passed. Self-hosting and produced-SDK consumer
cache recovery have separate evidence below.

Upstream references: [VMR build instructions](https://github.com/dotnet/dotnet/tree/b0f34d51fccc69fd334253924abd8d6853fad7aa#building),
[source-build requirements](https://github.com/dotnet/source-build/blob/main/Documentation/system-requirements.md).

## Generated package handoff

`msbuild_generated_nuget_package` consumes a declared Bazel action's `.nupkg`
output. Package ID and version remain explicit analysis-time inputs; the NuGet
content hash is computed from the produced bytes during extraction. Source-file
archives are rejected by this rule. Acquired archives still use
`msbuild_nuget_package` with mandatory SHA-256 and NuGet content hashes.

```python
msbuild_generated_nuget_package(
    name = "source_package",
    package_id = "Source.Package",
    version = "1.0.0",
    archive = ":pack",
)
```

Use this package in `deps`, `build_deps`, or other existing package roles and in
an explicit `msbuild_package_lock`. Declaring a package in the lock alone does
not authorize it as a project's direct dependency.

The `tests/source_sdk/package_handoff.py` synthetic uses actual SDK `Pack`
through `msbuild_generate`, then consumes the resulting package offline. On
macOS ARM64 / Bazel 9.2.0 / downloaded SDK 10.0.400, initial execution and body-edit
execution passed; mismatched package identity, missing producer output, and a
source-file archive were rejected. Thirteen package extraction unit checks also
passed, including the new generated content-hash, identity and path controls.
This establishes the handoff mechanism, not a real upstream SDK component build.

## Upstream baseline issues

The initial preparation failed because the minimal toolchain image lacked
`file`. Adding the pinned source's native prerequisites and `file` allowed its
binary scan to complete; it removed 743 disallowed checked-in binaries.

The first source build failed in IdentityModel: its wall-clock-derived file
version became `8.0.0.70927`, exceeding the valid revision range. The qualification
patch in `tests/source_sdk/patches/identitymodel-file-version.patch` passes
`FileVersion=<declared release version>.0` to that component's nested builds.
It does not disable compiler warnings or source-build binary checks.

Retrying the failed tree exposed external-package patch stamps surviving while
`PrepareInnerClone` recopied original source files. The current attempt uses a
fresh extraction and fresh package state. The bootstrap archive and SDK are the
only reused build inputs. `tests/source_sdk/baseline.sh` records the commands for
a fresh source tree; native package versions must be retained with its evidence.

## Real NoTargets source-package slice

`tests/source_sdk/notargets_handoff.py` packages the pinned upstream
`Microsoft.Build.NoTargets` 3.7.0 text payload using its original project, nuspec,
and `ManualNuspec.targets`. A small adapter supplies the upstream text-package
settings. This proves source package production and consumption, not the entire
Arcade/reference-package build.

The input directory contains `payload/`, copied from
`src/source-build-reference-packages/src/textOnlyPackages/src/microsoft.build.notargets/3.7.0/`,
and `ManualNuspec.targets`, copied from that repository's `eng/` directory.
The fixture checks each input against `pin.json` before use.

```sh
RULES_MSBUILD_BAZEL="$PWD/.tools/bin/bazelisk" USE_BAZEL_VERSION=9.2.0 \
  python3 tests/source_sdk/notargets_handoff.py /path/to/inputs /tmp/notargets-source
```

On macOS ARM64, the consumer imported the generated SDK successfully. Requesting
an unavailable version failed. Changing the producer's `UsingMicrosoftNoTargetsSdk`
property caused the consumer to rebuild and fail its assertion, proving that the
SDK implementation is an input to the consumer.

This exposed a projection bug: root `Sdk="Name/Version"` syntax cannot be copied
verbatim into an explicit `Import` element. The runner now uses MSBuild's
`SdkReference` parser to preserve the name, version, and minimum-version fields
on both implicit SDK imports.

The baseline limits `DOTNET_PROCESSOR_COUNT` to two after a six-processor attempt
exhausted the 8 GiB VM's practical memory budget and was interrupted. Native apt
package versions are recorded, but an immutable image containing those additions
has not yet been qualified. The successful exploratory run uses development version
metadata; the repeatable script pins release build ID `20251023.11` from the
hashed release manifest. Final release-version qualification is still required.

## Configured repository graph

After upstream preparation, run the evaluation probe in the Linux build
container:

```sh
python3 tests/source_sdk/evaluate_graph.py /path/to/vmr /tmp/configured-sdk.json
```

It validates the pinned definitions, then asks MSBuild for evaluated
`RepositoryReference`, `ProjectReference`, environment items, and build arguments.
It retains references with `BuildReference=false`; the reported SDK dependency
order includes only enabled edges. These are evaluation results, not a complete
execution plan: targets still discover package-version props, manifests, and
shipping/non-shipping assets.

Measured Linux ARM64 / Release source-only configurations:

| Selection | SDK dependency closure |
| --- | ---: |
| Shared components enabled | 22 repositories |
| `--shared-components=false` | 10 repositories |
| `--build-pass=2` | SDK only; other references retained as excluded |

This confirms that shared-component and build-pass conditions materially change
the graph and must be evaluated by MSBuild.

The synthetic generated-package cases and all three real NoTargets cases also
passed on Linux ARM64 with Bazel 9.2.0. Apple Container masks under `/proc` and
`/sys` prevented nested sandbox mounts. Qualification used a **private mount
namespace** with those child mounts removed; Bubblewrap and Bazel's Linux
sandbox remained enabled. An init/subreaper (`tini -s`) was needed to reap Bazel
server processes when testing inside the container whose main process is
`sleep`. The first synthetic run completed its five assertions but its shutdown
failed without that reaper; the real NoTargets run exited successfully with it.

## Full upstream baseline and produced-SDK consumers

The bounded upstream build succeeded with zero reported warnings/errors in
**25m 38.77s** wall time. This excludes source acquisition and preparation, and
includes `--clean-while-building`. GNU time reported maximum resident set size
2,258,448 KiB; this is not the aggregate peak memory of the container. The SDK
archive is identified in [the evidence summary](source-sdk-evidence.json).
Upstream's final check found zero files in its prebuilt-packages directory.

The produced Ubuntu 22.04 ARM64 SDK reports SDK `10.0.100-dev`, MSBuild `18.0.2`,
and both Microsoft.NETCore.App and Microsoft.AspNetCore.App `10.0.0-dev`.
This is an actual upstream source build, with the IdentityModel patch above.
It is not yet a Bazel build of the full SDK component graph.

```sh
python3 tests/explicit_msbuild/generated_sdk.py /tmp/source-sdk-consumer \
  --archive /path/to/dotnet-sdk-10.0.100-dev-ubuntu.22.04-arm64.tar.gz \
  --sdk-version 10.0.100-dev --runtime-version 10.0.0-dev
python3 tests/source_sdk/consumer_scenarios.py /tmp/source-sdk-consumer
```

The archive mode registers only the produced SDK, retaining its host, SDK,
reference packs, shared frameworks, workload metadata, templates, `dnx`, and
license files. The runner is compiled with that SDK. Bazel 9.2.0 on the qualified
Linux container passed:

- Library-to-app build and test execution using the produced runtime.
- Cached reuse with fetching disabled (`--nofetch`); this is not fresh offline
  reconstruction or remote-cache recovery.
- A body edit causing the test to fail, and an API edit causing compilation to fail.
- SDK `Pack`, generated package extraction, restore and consumer test execution.
- Razor generation, ASP.NET framework resolution, and actual view rendering.
- Framework-dependent `Publish` and execution of the published app.

The publish case required exposing `executable=True` on `msbuild_generate` so it
can preserve executable semantics while invoking custom targets. This small
publish fixture does not qualify general deployment, self-contained publish,
trimming, AOT, workloads, or other distributions/architectures.

## Produced-SDK remote-cache recovery

`tests/source_sdk/cache_recovery.py` seeds an HTTP cache with remote reads
disabled, then copies the consumer sources to another workspace and uses fresh
Bazel output/user roots, no local disk cache, and read-only remote-cache access.
Every logged recovery action must be a cache hit. Recovered artifact hashes
must agree with the producer, and a final invocation forces all three tests to
execute. Test XML generation is counted separately from actual test execution.

```sh
python3 tests/source_sdk/cache_recovery.py /tmp/source-sdk-consumer \
  /tmp/source-sdk-cache --cache http://cache-host:8080
```

With the pinned `bazel-remote` cache in a separate Apple Container, the measured
Bazel 9.2.0 runs took 34.55s to seed, 17.84s to recover, and 6.98s to force tests.
These wall times include batch Bazel startup and concurrent upstream self-hosting
work. They are correctness measurements, not an isolated performance comparison.
The recovered actions include SDK extraction, runner bootstrap, package generation
and extraction, application compilation and tests. Recovery used another path
in the same Linux VM, not another build machine. This does not establish cache
behavior for the SDK source-component graph itself.

## Declared full-source producer qualification

`source_action_prepare.py` creates separate content-hashed archives for the
pinned VMR sources, the prepared RC2 bootstrap SDK/packages, and the native
compiler/distribution filesystem. The qualifier's `source_sdk` rule uses the
existing isolated native-build driver, with an optional bootstrap overlay. Its
child process sees only those archives, writable source/scratch directories,
`/proc` and `/dev`; network access is isolated.

```sh
python3 tests/source_sdk/source_action_prepare.py /path/to/vmr.tar.gz \
  /path/to/prepared-baseline /tmp/source-sdk-action
cd /tmp/source-sdk-action
bazel test //:smoke
```

This graph directly connects the SDK source producer, SDK layout, `msbuild_sdk`,
and an app test. The controller compiles with an explicitly selected downloaded
SDK, so it does not depend on the SDK being produced. Both tool and runtime
configurations use the source producer in the execution configuration; `aquery`
confirmed exactly one `SourceSdkBuild` action. Controller compilation and graph
analysis passed. The full isolated build and app test also passed on Linux ARM64
with Bazel 9.2.0: **28:45.043** end-to-end, including **27:09.79** inside upstream
`build.sh`. The SDK reports `10.0.100`, MSBuild `18.0.2`, and runtime/ASP.NET
`10.0.0`; the final prebuilt-package check found zero files. Component probes ran
concurrently, and the baseline used development branding, so these runs do not
isolate Bazel overhead. The produced archive digest is in the evidence summary. The same archive also
passed all eight produced-SDK consumer checks above, including generated NuGet
packages, Razor rendering and execution of a framework-dependent publish.

Source/native/bootstrap archive timestamps use a fixed 1980 date because NuGet
rejects pre-1980 ZIP timestamps. Source archive rewriting also clears stale PAX
path metadata. The offline action sets `NuGetAudit=false` to avoid network-only
vulnerability lookups; this is not a vulnerability-audit qualification. Apple
Container required removing its masked proc/sys mounts in a private mount
namespace; Bubblewrap filesystem and network isolation remained enabled.

`source_action_recovery.py` recovered this producer and its app in a fresh
workspace/output/user root, with no local disk cache and remote uploads disabled.
All ten logged recovery spawns were cache hits, including the single
`SourceSdkBuild`; the recovered SDK archive hash matched. Recovery took **66.05s**,
including fresh Bazel setup. An app body edit took **16.54s** and an app API edit
**16.27s**; each executed only application compilation and test actions, retaining
the SDK archive unchanged. These are consumer edits, not SDK-component edits.
Recovery used another path on the same VM and a cache in another container.

```sh
RULES_MSBUILD_BAZEL=/path/to/bazelisk USE_BAZEL_VERSION=9.2.0 \
  python3 tests/source_sdk/source_action_recovery.py /tmp/source-sdk-action \
  /tmp/source-sdk-recovery --cache http://cache-host:8080
```

This first producer deliberately treated the upstream SDK build as one action.
It uses the release build ID and RTM branding. The later component graph below
adds explicit handoff of upstream asset manifests, package-version props, SDK
overrides and shipping/non-shipping package directories; the single-action
baseline remains useful for comparison.

## Self-hosting and payload comparison

A fresh extraction of the same VMR revision and IdentityModel patch rebuilt the
SDK using the first build's SDK and previously source-built artifact bundle.
The upstream build succeeded with zero warnings/errors in **26:08.16**, using
`DOTNET_PROCESSOR_COUNT=2` and `--clean-while-building`. The initial RC2-bootstrap
build took 25:38.77. These are development-version qualification runs, not an
isolated bootstrap performance comparison.

```sh
./prep-source-build.sh --no-sdk --no-bootstrap --no-artifacts --no-prebuilts \
  --with-sdk /path/to/first-sdk
# Preparation also needs the first produced artifact archive under
# prereqs/packages/archive/Private.SourceBuilt.Artifacts.Selfhost.tar.gz.
DOTNET_PROCESSOR_COUNT=2 ./build.sh -sb --clean-while-building \
  --with-sdk /path/to/first-sdk --with-packages /path/to/first-artifacts \
  --source-repository https://github.com/dotnet/dotnet \
  --source-version b0f34d51fccc69fd334253924abd8d6853fad7aa \
  --configuration Release --arch arm64 /p:BuildInParallel=false
python3 tests/source_sdk/compare_payloads.py first-sdk.tar.gz second-sdk.tar.gz comparison.json
```

The second SDK reports the same SDK/runtime versions. Registering that second
archive with `generated_sdk.py` passed app build, fetching-disabled reuse, body
edit test failure, and API edit compilation failure. Its archive digest is in
[the evidence summary](source-sdk-evidence.json).

Payload comparison ignores tar/gzip metadata and compares file bytes, modes and
link targets: both SDKs contain 5,143 files, with 3,873 identical and 1,270 changed;
none were added or removed. **The SDK payloads are not byte-identical.** Bootstrap
SDK/packages and workspace path differ between the builds, so this is a
self-hosting comparison, not a reproducibility test with identical inputs.
The cause of the changed binaries has not been isolated.

## Identical-input reproducibility check

A fresh Bazel output base rebuilt the isolated RTM SDK with cache reads and
uploads disabled. Execution logs show the same 4,915 declared input entries,
command arguments and environment variables for `SourceSdkBuild`. The rebuilt
SDK passed its app test, but **its payload is not byte-for-byte reproducible**:
4,848 of 5,149 files match, and 301 differ (268 DLLs, 24 JSON files and nine NuGet
packages). No files were added or removed. This comparison ignores archive
headers and checks file bytes, modes and link targets.

The repeat took 2,396.143 seconds, overlapping a component probe that caused
memory pressure. This is correctness evidence, not a performance comparison.
All 24 changed `.deps.json` files were parsed: their only semantic differences
are NuGet package SHA-512 values (498 changed fields across 110 distinct field
paths), although entry order also changes. Seven of the nine changed shipped
NuGet archives contain the same non-metadata members and differ in package
metadata; the other two contain changed task binaries or manifests. The 268
changed DLL paths represent 253 distinct before/after binary pairs, so most
are not just repeated copies. The cause of those compiled-binary differences
is not yet isolated. Package metadata normalization alone would not make the
SDK byte-identical.
Successful cache recovery demonstrates reuse of one stored output, not that
independent executions produce identical bytes. See the machine-readable
[repeat evidence](source-sdk-evidence.json).

The full component graph provided another repeat of SBRP while Bazel configured
it as a tool for the produced-SDK consumer. Its selected source archive was the
same, but this was a different Bazel action configuration, so it is not an
identical-action test. Comparing the two SBRP bundles found 192 changed files
at shared paths and four changed path names. All 190 NuGet archives changed;
their ZIP timestamps and generated core-properties IDs differ. After ignoring
NuGet relationship and core-properties metadata, 18 archives still contain
changed payload files, including managed assemblies. The two extracted SDK
layouts also carry changed package metadata. We have not isolated why those
assemblies differ; normalizing archive metadata alone would not make this
component byte-identical.

## Component output boundary

`tests/source_sdk/component_outputs.py` packages one component's original asset
manifests and the files they identify, preserving VMR-relative paths. Additional
side-output directories must be declared explicitly with `--extra-tree`.
Current manifests provide `PipelineArtifactPath`; the version-3 package manifests
used by WPF and WinForms use the upstream shipping/non-shipping package layout.
Missing artifacts, paths escaping the source root, and mismatched repository
origins are rejected. Manifest contents remain unchanged for upstream MSBuild to
interpret package versions and SDK overrides.

```sh
python3 tests/source_sdk/component_outputs.py /path/to/baseline arcade arcade.tar
python3 tests/source_sdk/component_outputs.py /path/to/baseline source-build-reference-packages sbrp.tar \
  --extra-tree prereqs/packages/reference
```

Auditing all 22 evaluated components in the successful development baseline found
410 retained files totaling 2,489,239,575 bytes, with no missing artifact paths.
This includes manifests as well as packages and blobs. Synthetic checks cover
stable bundle metadata, both manifest formats, missing files and path/origin
rejection. Bundle creation also passed on actual Arcade, SBRP and CommandLine
outputs. SBRP also copies 164 reference-only package files outside its publishing
manifest; its declared `prereqs/packages/reference` side output is required.

`component_replay_prepare.py` prepares a fresh isolated CommandLine build with
those Arcade and SBRP bundles. It passed with zero warnings/errors and produced
`System.CommandLine` and `dotnet-suggest` 2.0.0-dev. The component build command
took **10.34s**, excluding preparation; its log identifies only CommandLine as a
built component. The replay explicitly builds the shared orchestration task
assembly, restores the orchestration projects, invokes upstream
`ExtractToolPackage` for dependency SDKs, and disables dependency component
rebuilding. Outer whole-SDK publishing is disabled; inner component packaging
remains enabled. Source inputs still include the whole VMR, so this does not yet
prove component-specific source invalidation or scheduling all 22 components.

## Three-component Bazel graph

`component_graph_prepare.py` prepares explicit SBRP → Arcade → CommandLine
source actions. Each action consumes its own implementation, shared VMR build
metadata, the pinned bootstrap/native inputs, and declared dependency output
bundles. Dependency bundles are mounted read-only outside the source tree until
upstream preparation finishes, then copied into the writable build tree. MSBuild
still interprets their manifests and performs SDK/package setup.

The Linux ARM64 / Bazel 9.2.0 graph passed with RTM branding and the pinned
`20251023.11` build ID. The app consumed the produced `System.CommandLine` 2.0.0
package through `msbuild_generated_nuget_package`. The full graph and test took
**284.30 seconds**; inner component build commands took 130.98 seconds for SBRP,
17.11 seconds for Arcade and 8.27 seconds for CommandLine. The difference includes
archive staging, preparation, task compilation, dependency setup, Bazel overhead
and the app build/test. These are qualification timings, without a paired raw
MSBuild comparison.

```sh
python3 tests/source_sdk/evaluate_graph.py /path/to/pinned-vmr /tmp/evaluated-graph.json
python3 tests/source_sdk/component_graph_prepare.py /path/to/source-action /tmp/component-graph \
  --graph /tmp/evaluated-graph.json --native-tools /path/to/reviewed-native.tar \
  --through command-line-api
# In the generated workspace, with the Linux namespace prerequisites above:
bazelisk --batch test //:consumer --jobs=1 --disk_cache= --remote_cache=http://cache:8080 \
  --remote_cache_async=false --remote_download_outputs=all
RULES_MSBUILD_BAZEL=/path/to/bazelisk USE_BAZEL_VERSION=9.2.0 \
  python3 /path/to/rules/tests/source_sdk/component_edits.py /tmp/component-graph /tmp/component-edits \
  --output-base /tmp/component-edits-base --cache http://cache:8080
```

This was the first three-component qualification. The source selector keeps
other repositories' project/build metadata for upstream evaluation, excluding
their implementation files. Small tests prove that another component's body edit
does not change the selected archive bytes. The selector and output contracts
have since been extended through the complete 22-component graph below.
The generator now reads the configured graph produced by MSBuild evaluation;
`--through` selects one component and its transitive dependencies. It rejects a mismatched
source revision, configuration, missing dependency or native archive containing
private host material. This is graph generation for qualification; the selected
component's build remains an upstream MSBuild invocation.

The source-component edit/cache checks passed:

| Case | Wall time | Observed result |
| --- | ---: | --- |
| Body edit | 55.20 s | Only CommandLine rebuilt; removing the default version option caused the consumer test to fail as expected. |
| API edit | 56.70 s | Only CommandLine rebuilt; the app compiled and ran using the added public property. |
| Remote recovery | 27.01 s | All 12 logged spawns were cache hits, including all three component producers. |

SBRP and Arcade output hashes remained unchanged across edits. Recovery used a
new workspace, output base and user root on the same machine, no disk cache, and
remote uploads disabled; all three recovered component bundle hashes matched.
The HTTP cache ran in a separate container. This qualifies remote caching, not
remote execution. Edit times include fresh archive extraction and preparation;
the prototype does not retain a warm MSBuild component workspace.

## Configured component graph expansion

The generator now consumes `evaluate_graph.py`'s MSBuild-evaluated repository
graph and `BuiltSdkPackage` items instead of naming dependency edges or SDK
layouts in Python. It validates the pinned
revision, Release/ARM64 source-only configuration, complete build pass, and
topological dependency order before producing Bazel actions. An explicit
`--through` argument selects one component and its dependency closure. The native
archive is supplied separately and must exclude private host material.

The first extension through **Cecil** passed on Linux ARM64 / Bazel 9.2.0.
SBRP and Arcade were remote cache hits; only Cecil ran locally. Its inner build
took **7.62 seconds**, and the entire fresh Bazel invocation took **62.04
seconds**, including toolchain recovery and staging. Cecil published its
manifest and `Microsoft.DotNet.Cecil.0.11.5-alpha.25523.111.nupkg` in a declared
component bundle. Cecil's closure contains **three** components; CommandLine
follows Cecil in the evaluated SDK order.

The next selected closure, **Runtime**, passed with SBRP, Arcade and Cecil from
the HTTP cache; CommandLine and Runtime ran locally. Runtime published 146 files
totaling 1,343,985,144 bytes, including Linux native packs and framework
packages. Its inner build took **22:22.92**, and the fresh Bazel invocation took
**24:25.37**. This is a cold component build with `DOTNET_PROCESSOR_COUNT=1`;
there is no paired coarse-SDK timing from the same conditions.

XDT exposed a missing output boundary: its source-built SDK resolver needed the
extracted `Microsoft.Build.NoTargets` directory, while the earlier SBRP bundle
only carried its package. SBRP now declares the extracted NoTargets and Traversal
SDK directories as side outputs. A baseline bundle check retained all 15 files
from those directories. The XDT retry passed: its own build took **6.82 seconds**;
the Bazel invocation took **4:34.15** because SBRP and Arcade rebuilt after the
output contract changed. The first XDT attempt failed with `MSB4242` and is not
reported as a pass.

The graph generator can extend an existing qualification workspace. It verifies
the evaluated graph, bootstrap/native inputs and existing generated scripts,
then adds only new source archives and targets. This preserves local Bazel action
state and avoids duplicating large runtime inputs for each slice.
`--refresh-output-contracts` explicitly migrates an earlier evaluated graph
that lacks `BuiltSdkPackage` items; it rejects changes to the source revision,
configuration and dependency edges.

MSBuild evaluation identifies two built SDK packages from SBRP and three from
Arcade. The generator declares the corresponding extracted SDK directories as
component side outputs. Arcade passed with a 194-file, 18,200,955-byte bundle;
169 files came from its three extracted SDK layouts. This records the layouts
that downstream SDK resolvers read, alongside the published NuGet packages.

**SymReader** then passed from the extended workspace. Its upstream build took
**8.06 seconds** and the Bazel invocation took **50.74 seconds**. It published
its manifest and `Microsoft.DiaSymReader.2.2.0-beta.25523.111.nupkg`. Because
SBRP's output contract changed after the Runtime measurement, a cumulative
build must requalify Runtime and its downstream consumers against the new SBRP
bundle; the earlier Runtime pass remains evidence for its original input set.

The cumulative closure through **Roslyn** now passes with the expanded SBRP and
Arcade SDK-layout outputs. Runtime rebuilt under these declared inputs in
**22:36.41** of upstream build time and emitted 146 files totaling 1,343,987,291
bytes. SymReader rebuilt after its dependency bundle changed. Roslyn then built
in **2:18.87**, publishing 26 files totaling 62,131,566 bytes. The entire Bazel
invocation took **29:11.87**, including the runtime rebuild and all staging.
This qualified eight components together before the full graph run below.

**MSBuild** and **NuGetClient** then passed as separate actions in that order.
MSBuild's upstream build took **40.32 seconds** and its Bazel invocation
**1:33.86**; its eight-file bundle contained 7,530,906 bytes. NuGetClient's
upstream build took **26.89 seconds** and its Bazel invocation **2:01.87**;
its 20-file bundle contained 3,242,645 bytes. The NuGetClient invocation also
rebuilt XDT after its predecessor output contract changed. The cumulative
qualified workspace now has ten components.

**ASP.NET Core** passed next in **2:47.45** upstream and **3:49.81** Bazel wall
time, publishing 55 files totaling 377,211,788 bytes. **DeploymentTools**
passed in **6.19 seconds** upstream and **48.60 seconds** Bazel wall time,
publishing its manifest and package.

The first isolated **FSharp** run failed late in packaging: an inner
`FSharp.Core` netstandard2.1 build requested `UpdateXlf`, which it did not
import. The pinned FSharp source documents Linux Xliff limitations. Its
upstream `--ci` option disables local translation-file updates for release
builds. Passing that option to the FSharp component build resolved the failure
without changing other components' scripts. The retry passed in **4:26.42**
upstream and **5:13.61** Bazel wall time and published its manifest and
FSharp package. This is a component-specific upstream build mode, recorded as
an explicit action input.

The remaining components—Razor, SourceLink, Templating, Diagnostics, VSTest,
WinForms, WPF, WindowsDesktop and SDK—passed in the same generated workspace.
The final `//:sdk` bundle held 45 files (588,119,628 bytes), including the
564,899,505-byte `dotnet-sdk-10.0.100-ubuntu.22.04-arm64.tar.gz`. Its upstream
build took **3:50.55** and the Bazel invocation took **4:55.87**. All 22
component names, bundle digests, payload sizes and inner-build times are in the
[component graph results](source-sdk-component-graph-results.json). These
actions were qualified incrementally with local state and an HTTP action cache;
there is no single cold full-graph timing yet.

The 22 recorded upstream build commands total **42:00.42** when summed once
per component, of which Runtime accounts for **22:36.41**. The earlier raw
source-build baseline took **25:38.77** wall time. That baseline used two .NET
processors and development branding, while these component actions used one
processor and RTM branding, so these figures do not isolate Bazel overhead or
establish a matched speed ratio. A fresh full-graph run under matched resources
is still needed for a performance comparison.

The first SDK component attempt failed while constructing the redist Crossgen
layout because its Razor tasks output had not yet been built. The narrow
`sdk-redist-razor-reference.patch` adds the missing Razor tasks project edge to
the pinned SDK's redist project. That patch is part of the SDK action's declared
source archive. The corrected SDK action passed and published its original
upstream SDK archive; no prebuilt Razor tasks were supplied.

```sh
python3 tests/source_sdk/component_graph_prepare.py /path/to/source-action /tmp/component-graph \
  --graph /tmp/evaluated-graph.json --native-tools /path/to/reviewed-native.tar \
  --through sdk
# In the generated Linux ARM64 workspace with the namespace setup above:
bazelisk --batch build //:sdk --jobs=1 --disk_cache= \
  --remote_cache=http://cache:8080 --remote_cache_async=false \
  --remote_download_outputs=all
```

The complete graph remains a pinned qualification, not yet a general
source-built SDK distribution contract. The same-path bundle handoff preserves
upstream MSBuild, package and SDK behavior. Its independent cache recovery and
consumer checks follow; the identical-input repeat above was not byte-identical.

## Component-produced SDK consumer and recovery

With `--sdk-consumer`, the generator extracts the SDK archive from the final
component bundle, creates an SDK layout, registers it through `msbuild_sdk`,
and builds a normal SDK-style library and console app with `msbuild_library`
and `msbuild_test`. The downloaded controller SDK still compiles the source
action driver; the app toolchain uses the component-produced SDK. The app test
passed and printed `SDK_FROM_COMPONENTS=10.0.0`. The logged library and app
`MSBuildAssembly` actions both invoke `layout/dotnet`, and the test launch
manifest selects `produced_runtime.runtime/dotnet`.

The Linux ARM64 seed run took **7:09.87**: 20 component actions were HTTP
cache hits, while Razor and SDK ran locally and uploaded to a writable cache.
This is a partly cached seed, not a cold full-graph timing. An earlier
consumer attempt was interrupted by host disk exhaustion during Razor; it
completed after disk recovery, but its segments are not combined into a wall
time. The SDK bundle in the final seed has SHA-256
`99c155b5a511149d4bc1c960ae3134ec1ce85de95d6eb0fbfe7ab2e5e5b8be5d`.

```sh
python3 tests/source_sdk/component_graph_prepare.py /path/to/source-action /tmp/component-graph \
  --graph /tmp/evaluated-graph.json --native-tools /path/to/reviewed-native.tar \
  --through sdk --sdk-consumer
# In the generated Linux ARM64 workspace with the namespace setup above:
bazelisk --batch test //:smoke --jobs=1 --disk_cache= \
  --remote_cache=http://cache:8080 --remote_cache_async=false \
  --remote_download_outputs=all --test_output=all
RULES_MSBUILD_BAZEL=/path/to/bazelisk USE_BAZEL_VERSION=9.2.0 \
  python3 /path/to/rules/tests/source_sdk/component_consumer_probe.py \
  /tmp/component-graph /tmp/component-consumer-probe \
  --output-base /tmp/component-seed-base --cache http://cache:8080
```

The final probe measured a library body edit at **15.60 seconds** (the changed
return value made the test fail), an API edit at **17.42 seconds** (the old
caller failed compilation), and the corrected caller at **16.00 seconds**
(pass). No SDK component rebuilt for these edits. A new workspace with an
empty Bazel output and user root, no local disk cache, and remote uploads
disabled recovered the SDK and cached test in **48.99 seconds**. All 33 logged
actions were cache hits, including all **22** component producers; the SDK
bundle digest matched. Forcing the test process to execute then passed in
**18.42 seconds** and printed the same runtime version, while build actions
stayed cached. These runs used the same machine and an HTTP cache in a separate
Apple container; they do not qualify remote execution.
