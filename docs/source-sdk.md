# Building the SDK from source

Revision `b0f34d51fccc69fd334253924abd8d6853fad7aa` of `dotnet/dotnet`
builds a .NET SDK 10.0.100 on Ubuntu 22.04 ARM64 with Bazel 9.2.0. The
22-component Bazel graph produces an SDK that builds and runs an app.
The default downloaded SDK remains unchanged; both use the
[SDK artifact contract](sdk-toolchains.md). This is a qualified source build,
not a general source-built SDK distribution or a cross-platform claim.

The [pin](../tests/source_sdk/pin.json) fixes the source archive, bootstrap
versions, container image, native prerequisites and reviewed upstream definitions.
The build still needs a bootstrap SDK and source-built artifact packages. MSBuild
evaluates `RepositoryReference` and `ProjectReference` conditions before Bazel
generates component edges. The source-only Release/ARM64 closure has 22
repositories with shared components, or 10 with them disabled; copying XML
references directly would miss those conditions and generated package metadata.

## Current result

The complete graph builds the upstream SDK archive with 22 separate source
component actions. The SDK component also declares the expanded `dotnet` layout
as outputs, removing two later archive-extraction actions. Earlier components
retain their original manifest and package outputs. The final SDK action emitted
4,786 SDK files; its consumer's library and app compiled with that `dotnet`, and
its test launched the produced runtime and printed `SDK_FROM_COMPONENTS=10.0.0`.
The downloaded controller SDK only builds the Bazel source-action driver.

A fresh consumer workspace with empty Bazel output/user roots, no disk cache and
remote uploads disabled recovered all **31** logged actions from an HTTP cache,
including all **22** components. The recovered SDK bundle SHA-256 matched the
seed (`b9c79ae5393fc5215af934bfa75fa10af7b35c9248e42ced6aa044a0e16937f6`).
Forcing the recovered test process to execute passed with build actions still
cached. This is same-machine cache recovery, not remote execution.

The earlier single-action source-produced SDK also passed application
build/test, an SDK `Pack` and package consumer, Razor view rendering, ASP.NET
framework resolution, and a framework-dependent `Publish` that ran. In the
component graph, consumer body and API edits invalidated only the affected
application actions; no SDK component rebuilt. These are
bounded fixtures, not qualification of arbitrary workloads, publish modes,
trimming, Native AOT or another architecture.

| Observation | Result | Interpretation |
| --- | ---: | --- |
| Raw upstream SDK build | 25:38.77 | Development branding, two .NET processors; excludes acquisition/preparation |
| First one-action Bazel source build | 28:45.04 | Includes 27:09.79 in upstream `build.sh`; separate baseline |
| Sum of 22 recorded component build commands | 42:00.42 | One processor and RTM branding; not comparable with raw wall time |
| Direct-layout seed | 313.84 s | Partly cached: one local SDK action, upstream components cached |
| Independent direct-layout recovery | 40.31 s | All 31 actions hit HTTP cache |
| Forced recovered test execution | 13.30 s | Compilation stayed cached |
| Library body / API / repaired API edit | 15.60 / 17.42 / 16.00 s | Application edits, not SDK component edits |

No matched cold full-component-graph versus raw-MSBuild benchmark exists. The
[component results](source-sdk-component-graph-results.json) retain each
component's output digest, size and inner build time; the
[evidence summary](source-sdk-evidence.json) retains the archive and repeat
comparisons. Do not use the table above as an isolated Bazel overhead estimate.

## How the component handoff works

`evaluate_graph.py` asks MSBuild for the configured repository graph and
`BuiltSdkPackage` items. `component_graph_prepare.py` selects the requested
component and its dependency closure; `--through sdk` selects the full graph.
Each Bazel action receives declared source, bootstrap and native inputs plus
read-only dependency bundles. Upstream MSBuild still interprets asset manifests,
package-version props, SDK overrides and shipping/non-shipping package paths.
The graph generator rejects a different source revision, configuration,
dependency order or unreviewed native archive.

`component_outputs.py` preserves upstream manifests and their files at VMR-relative
paths. Required side outputs include SBRP's extracted NoTargets and Traversal SDKs,
reference packages, and Arcade's extracted SDK layouts. Missing artifacts, escape
paths and wrong repository origins fail. The successful 22-component baseline
identified 410 retained files (2,489,239,575 bytes). This is a bounded output
contract, not a general dependency-closure algorithm.

The pinned source needed two narrow patches: `identitymodel-file-version.patch`
sets a valid declared file version instead of a wall-clock-derived revision,
and `sdk-redist-razor-reference.patch` adds a missing Razor tasks project edge to
the SDK redist build. FSharp uses upstream `--ci` to avoid Linux Xliff updates.
The first baseline also required `file` in the native image. These are declared
qualification inputs; they do not disable compiler warnings or source-build
binary checks. The final upstream check found zero prebuilt-package files.

## Generated package handoff

`msbuild_generated_nuget_package` consumes a declared `.nupkg` action output.
Package ID and version are explicit Bazel inputs; extraction computes the NuGet
content hash from produced bytes. The package still needs an explicit dependency
role and `msbuild_package_lock`; a lock entry alone is not a direct dependency.
Source-file archives, missing outputs and wrong package identities are rejected.
Acquired archives instead use `msbuild_nuget_package` with mandatory archive and
NuGet content hashes.

```starlark
msbuild_generated_nuget_package(
    name = "source_package",
    package_id = "Source.Package",
    version = "1.0.0",
    archive = ":pack",
)
```

The synthetic SDK `Pack` fixture passed initial and body-edited builds on macOS
ARM64. A real pinned `Microsoft.Build.NoTargets` 3.7.0 source-package producer
and consumer passed on macOS and Linux ARM64. The `Sdk="Name/Version"` projection
also had to preserve MSBuild's parsed SDK name, version and minimum version when
rewritten as explicit imports. These cases prove package handoff, not the whole
SDK build.

## Reproduce

Use the pinned inputs and fresh paths from `pin.json`. `baseline.sh` documents
the raw source-only build. In an Ubuntu 22.04 ARM64 environment with the native
packages and bootstrap prepared:

```sh
python3 tests/source_sdk/inventory.py /path/to/vmr /tmp/sdk-inventory.json
python3 tests/source_sdk/evaluate_graph.py /path/to/vmr /tmp/sdk-graph.json
python3 tests/source_sdk/source_action_prepare.py /path/to/vmr.tar.gz \
  /path/to/prepared-baseline /tmp/source-sdk-action
python3 tests/source_sdk/component_graph_prepare.py /tmp/source-sdk-action \
  /tmp/component-graph --graph /tmp/sdk-graph.json \
  --native-tools /path/to/reviewed-native.tar --through sdk --sdk-consumer
cd /tmp/component-graph
bazelisk --batch test //:smoke --jobs=1 --disk_cache= \
  --remote_cache=http://cache:8080 --remote_cache_async=false \
  --remote_download_outputs=all --test_output=all
```

The direct-layout consumer and independent recovery controls are in
`tests/source_sdk/component_consumer_probe.py`. Run its help for path/cache
arguments. The package-only fixtures are `package_handoff.py` and
`notargets_handoff.py`; the component edit controls are `component_edits.py`.
Apple Container's masked `/proc` and `/sys` child mounts require a private mount
namespace before nested Bubblewrap; the recorded setup and full step-by-step
chronology remain in the [pre-condensation report](https://github.com/keegan-caruso/msbuild-bazel/blob/4ab387c59ddf5fda46d15646cf0f738d9a0026a0/docs/source-sdk.md).

## Remaining limits

The build is pinned to one VMR revision, Linux ARM64, SDK 10.0.100 and Bazel
9.2.0. It uses an isolated local MSBuild action per component, not remote
execution. Source selection retains shared build metadata; it has not proven
that every unrelated source edit leaves all component keys unchanged. The full
22-component cold graph has no matched raw comparison. Recovery from one cached
execution does not prove reproducible independent builds.

A second build of the same isolated RTM action, with identical declared inputs,
produced a valid SDK but different payload bytes: 4,848 of 5,149 files matched,
301 differed (268 DLLs, 24 JSON files and nine NuGet packages). Changed JSON
values include NuGet content hashes; some assemblies also differ. The cause is
not isolated. A separate self-hosting run using the first SDK and artifacts also
passed, but its bootstrap inputs changed and its payload is not byte-identical:
3,873 of 5,143 files matched. Neither comparison establishes deterministic
independent outputs, although HTTP caching reuses one recorded output.
