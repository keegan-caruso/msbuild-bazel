# Building the SDK from source

This qualification targets .NET SDK 10.0.100 on Linux ARM64, starting from
`dotnet/dotnet` revision `b0f34d51fccc69fd334253924abd8d6853fad7aa`.
The qualification builds a complete SDK in one isolated Bazel action and runs
an app with it. Per-component scheduling remains open. The default downloaded
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
Bazel component graph remains unqualified. Self-hosting and produced-SDK consumer
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

This first producer deliberately treats the upstream SDK build as one action.
It uses the release build ID and RTM branding. It does **not** establish per-repo
incremental builds: splitting its 22-component closure still requires explicit
handoff of upstream asset manifests, package-version props, SDK overrides and
shipping/non-shipping package directories. The configured graph probe and the
small generated-package producers provide the starting points for that work.

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
