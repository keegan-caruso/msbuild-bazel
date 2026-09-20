# Explicit Bazel rules: first implementation

The first executable slice of the [API design](explicit-bazel-api-design.md) is in
`msbuild/defs.bzl`, with a .NET host in `tools/ExplicitBuild`. This is an opt-in
path; the existing preparation/discovery workflow remains available. It has not
yet been qualified against the full Orchard graph or compared with raw MSBuild.

## Implemented boundary

- `msbuild_library`, `msbuild_binary`, and `msbuild_test` declare each project's
  sources, dependencies, SDK framework references, imports, configuration and items.
- `msbuild_items` carries a generic item type and metadata, including resource
  logical names. No application-specific item rules are introduced.
- Each assembly action invokes MSBuild for **one project**. Original project edges
  must agree with Bazel declarations. Project references are replaced with declared
  reference-assembly outputs. There is no application-wide qualification, graph
  export, preparation, or dependency-result replay on this path.
- Implementation DLLs and reference DLLs are separate outputs. Compilation consumes
  dependency references; launchers compose implementation outputs and runtime data.
- A toolchain supplies the SDK, runner and runtime closure. BUILD attributes accept
  ordinary Bazel `select()` configuration; this slice requires matching TFMs across
  project edges and the execution platform's SDK/apphost.
- `msbuild_nuget_package` extracts each locked archive once as a Bazel action.
  Its transitive package closure is explicit. Archive SHA-256 and NuGet restore
  content hashes are separate inputs because signed archives can have different
  byte hashes from NuGet's lock content hash. Identity and extraction paths are
  checked. Project actions use read-only package trees without re-extracting them.
- `deps` enables compile/runtime package assets; `build_deps` and `analyzers` enable
  their respective roles. A package can be named in multiple attributes. Each role
  currently applies to the named package target's declared closure.

A closed, single-project `Restore` still generates SDK/NuGet assets inside each
assembly action. It uses only declared packages and an empty feed list, with
network access denied. Removing this remaining per-project work is a future
optimization, not a result claimed here.

## Example

```starlark
load("@rules_msbuild//msbuild:defs.bzl",
     "msbuild_library", "msbuild_test", "msbuild_items")

msbuild_items(
    name = "resources",
    item_type = "EmbeddedResource",
    srcs = ["message.txt"],
    metadata = {"LogicalName": "message"},
)

msbuild_library(
    name = "Library",
    project = "Library.csproj",
    target_framework = "net10.0",
    srcs = ["Value.cs"],
    items = [":resources"],
)

msbuild_test(
    name = "Tests",
    project = "Tests.csproj",
    target_framework = "net10.0",
    srcs = ["Tests.cs"],
    deps = [":Library", "//packages:xunit.v3.mtp-v2"],
    build_deps = ["//packages:xunit.v3.mtp-v2"],
    analyzers = ["//packages:xunit.analyzers"],
    msbuild_properties = {"UseMicrosoftTestingPlatformRunner": "true"},
    data = ["test-settings.json"],
)
```

The runner setting above is an ordinary MSBuild property consumed by xUnit's
entry-point generator, not a test-runner selector in the Bazel rule.

`msbuild_test` executes `dotnet Tests.dll` from a private runtime directory. It
forwards arguments and exit status. Test execution does not invoke `dotnet test`,
restore, or MSBuild. The SDK still builds an apphost when required by xUnit's
build targets. Unsupported Bazel filtering and multiple shards fail explicitly;
VSTest adapters, coverage, MTP-to-Bazel XML conversion, and filter/shard translation
remain future work.

## Local toolchain setup and reproduction

Use the repository's pinned SDK 10.0.400 and Bazel 8.4.2. Set
`RULES_MSBUILD_DOTNET_ROOT` to the SDK directory and `RULES_MSBUILD_BAZEL` to the
Bazel executable, or use the Nix development shell.

```sh
bash scripts/dotnet.sh build tools/ExplicitBuild -c Release -warnaserror
python3 -m unittest discover -s tests/explicit_msbuild -v
python3 tests/explicit_msbuild/acceptance.py /tmp/explicit-acceptance
```

The acceptance harness writes a complete `MODULE.bazel` and registered toolchain
using the existing `local_dotnet_sdk` repository rule. It is also a concrete
bootstrap example. Runner binaries are built beforehand; SDK and lock-file
Bzlmod extensions and published runner bootstrap are not implemented yet.

For the real MTP application, acquire the test packages outside the build action:

```sh
mkdir -p /tmp/mtp-lock
cp tests/explicit_msbuild/fixtures/Mtp.csproj /tmp/mtp-lock/Mtp.csproj
bash scripts/dotnet.sh restore /tmp/mtp-lock/Mtp.csproj --packages /tmp/mtp-lock/packages
python3 tests/explicit_msbuild/mtp.py /tmp/explicit-acceptance /tmp/mtp-lock
```

This harness converts the resolved test asset graph into explicit package BUILD
rules, including archive digests. It does not provide a production lock generator.
`RULES_MSBUILD_REPOSITORY_CACHE` optionally reuses a Bazel download cache.
`RULES_MSBUILD_REMOTE_CACHE` runs the assembly acceptance against that HTTP cache
with the local disk cache disabled. Reports and execution logs stay under the
supplied acceptance directory.

## Observed results

Qualified on macOS ARM64 with the Nix SDK and Linux ARM64 in an Apple container
using `rules_msbuild-toolchain:arm64` (image digest prefix `47a9e2fed018`):

| Control | Result |
| --- | --- |
| Library → application, embedded resource, direct/transitive runtime data | Passed |
| Executable test pass, failure, unsupported filter | Passed / rejected as expected |
| Library method-body edit | Only library compiles; reference digest unchanged; application prints changed value |
| ProjectReference mismatch | Rejected |
| Custom target reads undeclared host file | File contents unavailable; negative control fails |
| Custom target writes source directory | Rejected |
| Delete producer state, relocate source, recover from disk cache | Both assembly actions hit; application runs |
| xUnit 4.0.0 with actual MTP v2 entry point, 16 locked packages | Pass → assertion failure → recovered pass |

On macOS, the same deleted-producer/relocated-source experiment also passed using
HTTP `bazel-remote` with the disk cache disabled. This proves the sampled
assembly/runtime cache boundary, not general cross-machine or Razor portability.

Repository checks also pass: `scripts/check.sh`, `scripts/check-dotnet.sh`
(including four package-integrity controls), and native acceptance. The macOS
workflow suite needs GNU `sha256sum` on PATH and permission to start its native
sandboxes. One pre-existing environment-dependent test is skipped.

## Limits and next qualification

The compile child uses `sandbox-exec` on macOS and `bubblewrap` on Linux. The
parent stages declared files outside Bazel's sandbox to avoid nested macOS
sandboxing. Remote execution is disabled. The local OS runtime is still part of
the supported environment: macOS system libraries/shell and Linux `/usr/lib` and
selected `/etc` files are exposed. A fully pinned remote execution image/platform
contract is still required; this is not a universal hermetic toolchain claim.

Initial project support is one C# SDK-style project with one root `Sdk` attribute,
one TFM, matching-TFM project references, and framework-dependent output.
Unsupported project-reference metadata and package metadata are rejected instead
of silently reinterpreted. PrivateAssets propagation, central package management,
project-built analyzers/tools, external-repository project-relative paths,
Windows, cross-compilation, publish/AOT and test protocol integration remain
unqualified. Scalar MSBuild properties cannot override reserved paths or graph
controls. Generated files should be declared labels; SDK-generated compilation
items can still be created inside the action.

Next: add pinned SDK/lock extensions; qualify generic Razor/resource imports and
representative Orchard targets; then measure cold, unchanged, source-edit and
remote-hit timings against raw MSBuild. The design's larger performance goal
remains open.
