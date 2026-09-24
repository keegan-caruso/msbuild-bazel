# Runtime repository primitives

These generic rules cover the six capability gaps from the initial dotnet/runtime
source audit. They are qualified with small synthetic projects, not a build of
CoreCLR, CoreLib or dotnet/runtime's libraries and tests.

## Assembly contracts and configured edges

`msbuild_library` adds:

- `output_mode = "sdk"` (default): publish the SDK-generated reference assembly.
- `output_mode = "reference"`: compile a reference-only assembly; publish no
  runtime files. Consume it through a paired assembly or a reference pack.
- `output_mode = "implementation"`: compile without requesting an additional
  reference assembly; expose the implementation itself to compile consumers.
- `configuration`: an explicit MSBuild Configuration, otherwise the existing
  Bazel compilation-mode mapping applies.

```starlark
msbuild_library(
    name = "contract",
    project = "ref/Library.csproj",
    assembly_name = "Library",
    target_framework = "net10.0",
    srcs = ["ref/Library.cs"],
    output_mode = "reference",
)
msbuild_library(
    name = "implementation",
    project = "src/Library.csproj",
    assembly_name = "Library",
    target_framework = "net10.0",
    srcs = ["src/Library.cs"],
    configuration = "Release",
    output_mode = "implementation",
)
msbuild_assembly(name = "library", contract = ":contract", implementation = ":implementation")
```

A consumer's `ProjectReference` names the **implementation project** and its Bazel
`deps` selects `:library`. The compiler receives the contract closure; execution
receives the implementation closure. Assembly name, version, culture and public
key token must match. A reference-only implementation is rejected. This checks
assembly identity, not full API compatibility between independently authored
contracts and implementations.

An explicitly selected platform implementation may pair with a neutral contract
of the same base framework, for example `net10.0` → `net10.0-unix`. The pair keeps
the implementation's configured framework for dependency validation. Reverse
substitution, different platforms and different base versions remain rejected.
`tests/explicit_msbuild/platform_contracts.py` proves this boundary, unchanged
contract bytes across body edits, and test invalidation on Bazel 8.8 and 9.2.

Producers publish small identity records. Pair validation depends on these records,
so an implementation-body edit does not force validation or downstream compilation
when assembly identity and contract bytes remain unchanged. Ordinary SDK projects
retain their existing reference boundary and do not require pairing actions.

Select the implementation label directly when compiling against internals that the
public contract omits. This deliberately makes implementation bytes compile inputs.
Existing SDK-generated friend reference assemblies still work normally.

`SetConfiguration`, `SetTargetFramework`, and `AdditionalProperties` assignments on
compile `ProjectReference` edges are checked against the selected producer's
explicit configuration/framework/properties. Producer evaluation rejects local
overrides of those declared properties. Removing a consumer-declared custom
global property is supported only when the selected producer omits it. Removing
reserved runner globals remains rejected. Labels and `select()` select producers;
the rule does not discover variants or rebuild project dependencies internally.
The same configuration checks now apply to declared tools, analyzers and project
output items. Conflicting configurations for one project across dependency roles
are rejected. Aliases remain unsupported.

## Compile packs and runtime layouts

`msbuild_reference_pack(srcs = [...], assemblies = [...])` collects explicit DLLs
and reference outputs from local assembly producers. A project's
`reference_pack = ":pack"` disables implicit framework resolution and supplies only
these framework DLLs. It cannot be mixed with named `FrameworkReference` packs.
Framework assemblies are compile-only and are not copied into runtime outputs.
Pack analyzers and metadata imports remain separate explicit inputs.

A core library can use the existing scalar properties
`DisableImplicitFrameworkReferences=true`, `NoStdLib=true` with implementation
output mode. The fixture compiles a minimal replacement for predefined CLR types;
it is not a runnable System.Private.CoreLib.

`msbuild_layout(paths = {label: "destination", ...})` composes files and declared
artifact directories in a separate cached action. `"."` merges a directory at the
root. Destinations must be relative and conflicting contents fail. Byte-identical
duplicate files are permitted. Bazel expands declared tree artifacts into an
explicit file manifest; composition copies only those files, materializing sandbox
links as regular files. It never discovers inputs by walking symlink targets.
File modes are preserved, including native executable bits. Empty tree roots are
supported; empty subdirectories are not a portable part of Bazel tree artifacts. Each label must produce one file or
directory; use file labels/output groups for multi-output producers.

`layout_bindings = {":bootstrap_layout": "BootstrapRoot"}` binds a project's
MSBuild property to a staged, read-only layout directory, including a trailing
separator. It supports imports, generated task inputs and upstream artifact-path
properties. Reserved/duplicate properties and local overrides are rejected.
The layout is composed once, although the current action preparation still stages
its selected tree for each consumer. Keep layouts bounded; do not pass the entire
repository artifact directory to every project.

## Runtime under test

```starlark
msbuild_layout(name = "testhost_tree", paths = {":acquired_runtime_tree": "."})
msbuild_runtime(name = "testhost", layout = ":testhost_tree", entry_point = "dotnet")
msbuild_test(
    name = "tests",
    project = "Tests.csproj",
    srcs = ["Tests.cs"],
    target_framework = "net10.0",
    runtime_host = ":testhost",
)
```

`runtime_host` also applies to binaries. The selected executable receives the
managed DLL and normal test/application arguments. Its tree is a runtime/test
input, never a compilation input. `DOTNET_ROOT` and architecture-specific variants
point at that tree, `DOTNET_HOST_PATH` selects its host, and multilevel lookup is
disabled. A missing executable or
runtime component fails; the runner does not substitute its compiler SDK host.
`launch_mode = "dotnet"` is the default and retains existing host-wrapper behavior.
`launch_mode = "corerun"` sets `CORE_ROOT` to the selected layout before invoking
its host. Both pass the application DLL followed by its arguments. VSTest with
corerun is rejected because its separate testhost process needs a dotnet host;
executable tests and MTP can use corerun.

`msbuild_runtime` also accepts `runtime_identifier` and `version` identity metadata,
`env` for literal child-process environment values, and `data` for additional
runfiles. Host-selection variables (`CORE_ROOT`, `DOTNET_ROOT*`, `DOTNET_HOST_PATH`
and `DOTNET_MULTILEVEL_LOOKUP`) are reserved. These settings affect the application
process only, never the bootstrap SDK worker. Source runtime declarations should
set `target_compatible_with` for their actual platform; identity strings alone do
not configure or cross-compile a runtime.

Compile-pack selection and runtime selection are independent. When implicit
framework references are disabled, provide the runtime's required configuration
explicitly. The fixture uses the SDK's `runtimeconfig.template.json` mechanism via
an `msbuild_items` input, with a top-level `framework` object. No runtime version
is inferred from the compile pack. Existing runner/adapters, test settings, data,
environment and reporting controls remain available.

## Native tools and generated components

`msbuild_native_tool(layout = ":compiler_tree", entry_point = "gcc")` exposes a
native tool tree through the existing `tools` and `msbuild_file_binding` API. A
native tree is staged as ordinary files, rather than interpreted as a managed
assembly/package manifest. The entry point must exist. Its auxiliary binaries,
headers, sysroot and other required inputs must be declared by the caller.

Use existing Bazel native rules where suitable, or bounded `msbuild_generate`
actions when retaining upstream MSBuild targets/tasks. This does not introduce a
CMake implementation or a repository-wide shell build. The native fixture uses a
small declared MSBuild task to invoke a declared GCC tree and emits one freestanding
shared library. The generated library enters an executable test through
`data_paths`, so native/header edits do not invalidate managed compilation.
The fixture task verifies its expected compiler closure before invocation.

## Evidence and reproduction

Linux ARM64 / SDK 10.0.400 qualification passes **92 new synthetic cases**:
38 managed cases and 8 native cases on each of Bazel 9.2.0 and 8.8.0.
The existing worker acceptance (23 scenarios), friend-assembly suite (24 scenarios),
C# build/format and unit checks (36 tests), toolchain checks and Starlark lint also
pass. Existing integration regressions were rerun on Bazel 9.2.0.

See [runtime-primitives-evidence.json](runtime-primitives-evidence.json) for
per-case results, execution counts and loaded runtime identities.
The cases cover separate contracts, body/API changes, friend access, type forwarding,
assembly/configuration mismatch rejection, removed globals, two runtime trees,
missing hosts/components, explicit pack selection and missing-pack failure,
no-standard-library compilation, generated imports, read-only layouts, collisions,
missing outputs, native P/Invoke, tool/header mutation, and producer-deleted recovery.

Run inside the qualified Linux ARM64 toolchain environment:

```sh
export RULES_MSBUILD_DOTNET_ROOT=/opt/rules_msbuild-toolchain/.tools/dotnet
export RULES_MSBUILD_BAZEL=/tmp/bazel-9.2.0
bash scripts/check-dotnet.sh
python3 tests/explicit_msbuild/runtime_primitives.py /tmp/fresh-managed-probe
python3 tests/explicit_msbuild/native_components.py /tmp/fresh-native-probe
```

Repeat with the checksum-verified Bazel 8.8.0 binary. Native fixture setup needs
GCC/binutils; it snapshots compiler binaries into declared input files and records
their SHA-256 identities. The action uses no ambient compiler lookup. The qualified
worker still exposes the platform `/usr/lib` runtime roots; this does not establish
a portable native sysroot or cross-platform native-toolchain qualification.

Recovery here uses a disk action cache, a relocated source tree and a fresh output
base after deleting the producer; it is not the separate-VM remote-cache gate.
No CI, real runtime build, performance comparison, full API compatibility analysis,
source-built CoreCLR/JIT, IL SDK qualification, packaging, Mono/AOT/WASM or
cross-compilation is claimed. The subsequent
[source-only runtime qualification](runtime-source-host.md) covers selected real
projects and tests; it does not widen these synthetic results to other platforms
or the full upstream repository.

## Framework-closure follow-up

The Immutable net10 qualification adds three small generic capabilities/checks:

- Reference-only libraries can depend on other reference-only libraries. Their
  runtime directories remain empty. Executable/implementation consumers still
  require an implementation or an explicit reference pack.
- `msbuild_properties = {"UseSharedCompilation": "false"}` can opt out of the
  isolated worker's compiler-server default. Only Boolean values are accepted;
  other reserved properties retain their existing validation. Package-provided
  compiler paths differ between action closures, so a large graph can otherwise
  retain many compiler servers. This setting changes process lifetime, not the
  compiler, analyzers or declared inputs.
- Layout composition accepts real directory outputs from earlier Bazel actions.
  Bazel expands their children at execution time through `Args` and
  `DirectoryExpander`. The layout action is sandboxable and has no local-only
  execution requirement. It needs only the declared host runtime and runner,
  rather than the full SDK. See the sandbox qualification below.

The managed suite now passes **41 cases on each of Bazel 8.8.0 and 9.2.0**,
including reference chains, invalid compiler-sharing values, composition of a
layout from another layout, and relocated producer-deleted cache recovery.
See [follow-up evidence](runtime-framework-primitives-evidence.json). The earlier
native and integration evidence above belongs to its original run.

## Sandboxed layout composition

Run the focused fixture after building the runner:

```sh
source scripts/env.sh
python3 tests/explicit_msbuild/layout_sandbox.py /tmp/layout-sandbox-check
# Optional: use --remote-cache http://CACHE:8080 for HTTP cache recovery.
```

The fixture forces sandbox execution for cold and edited builds, checks the
execution log's runner, and uses a separate output base to verify cache recovery.
It covers generated trees composed twice, paths with spaces, an explicitly
declared source symlink, executable permissions and execution, empty layouts,
content edits, conflicting destinations, and path escapes. Recovered output files
must be regular files with executable permissions intact.

Producer tree validity follows Bazel's tree-artifact contract; composition no
longer attempts to distinguish producer links from sandbox-created links. The
remaining strict tree walk is used when staging composed layouts into MSBuild,
not when composing them.

Qualified on macOS ARM64 and Linux ARM64 with Bazel **8.8.0 and 9.2.0**,
using SDK 10.0.400. macOS used a disk cache; Linux used an HTTP cache. Both
versions executed the layout actions in their native sandbox. The existing
41-case runtime-primitives suite also passed on Linux ARM64 with Bazel 9.2.0,
including generated imports, read-only staging and producer-deleted recovery.
Remote execution eligibility is enabled, but this change does not claim an
actual remote-executor qualification.

## Downloaded and source-built runtime providers

Declare a verified runtime dependency in `MODULE.bazel`:

```starlark
dotnet = use_extension("@rules_msbuild//msbuild:extensions.bzl", "dotnet")
dotnet.runtime(name = "net10", version = "10.0.12")
use_repo(dotnet, "net10")
```

Select `runtime_host = "@net10//:runtime"` on an executable or test. The alias uses
Bazel's **target** platform constraints to select the application runtime. The
build SDK remains independently selected for its execution platform. The catalog
pins Microsoft archive URLs and SHA-512 integrity from
[release metadata](https://builds.dotnet.microsoft.com/dotnet/release-metadata/10.0/releases.json).
It includes 10.0.0 and 10.0.12 for Linux and macOS, ARM64 and x64; only ARM64 is
execution-qualified here. `platforms = ["linux-arm64"]` limits the declared set.
Unsupported platforms or unknown versions fail without selecting a host fallback.

For a private mirror or custom distribution, use `dotnet.runtime_archive` with
`name`, `version`, `platform`, `urls`, and mandatory `integrity` (Bazel SRI format).
The archive must contain a dotnet runtime installation at its root. This supplies
the same public `:runtime` target. Download/extraction uses Bazel's repository
cache. No source compilation runs during repository evaluation.

Source-built runtimes use the same provider:

```starlark
msbuild_runtime(
    name = "source_runtime",
    layout = ":core_runtime",
    entry_point = "corerun",
    launch_mode = "corerun",
    runtime_identifier = "linux-arm64",
    version = "10.0.0",
    target_compatible_with = ["@platforms//os:linux", "@platforms//cpu:aarch64"],
)
```

`:core_runtime` composes declared source-build outputs with `msbuild_layout`.
There is no downloaded/source switch in the consuming rule. Compilation uses
its separately declared reference pack and SDK. Editing the selected runtime
invalidates dependent tests while preserving application compilation when its
compile inputs are unchanged.

### Qualification commands

After building the runner and sourcing `scripts/env.sh`:

```sh
python3 tests/explicit_msbuild/runtime_downloads.py /tmp/runtime-download-check
python3 -m unittest discover -s tests/sdk_repository -p test_runtime_repository.py -v
```

The first fixture runs an actual downloaded 10.0.0 runtime and a generated host
wrapper through the same provider. It checks runtime identity, declared environment,
no-op caching, runtime-only edits with zero compilation actions, host failure,
and offline reuse after acquisition. The generated wrapper is synthetic; it is
not a source build of CoreCLR. The repository tests check a verified custom archive,
incorrect/missing integrity, and unsupported versions/platforms.

`tests/explicit_msbuild/runtime/provider_host.py PREPARED OUTPUT` prepares a small
corerun smoke test from the existing pinned v10.0.0 runtime qualification graph.
It uses the graph's native CoreCLR/JIT/corerun/System.Native outputs and managed
CoreLib/System.Runtime outputs, with no installed runtime payload. The application
checks that CoreLib loads from the selected layout and sees the declared runtime
environment and expected runtime payload marker. Build `//runtime:smoke` in the generated workspace. This is a consumer of the
bounded source-build rules, not a general dotnet/runtime bootstrap command.

The [SDK extension](development.md#using-the-rules-in-an-application) now acquires
SDKs and registers their bundled runtime as the default. Complete source-runtime
packaging, Windows/Mono/NativeAOT support, and rebuilding the entire SDK from source
remain outside this runtime-provider change.

Run `runtime/provider_controls.py WORKSPACE EVIDENCE --remote-cache URL` to check
the prepared source fixture's no-op, runtime payload mutation and restoration.
It preserves the original marker in a `finally` block. The Linux qualification
container needs a child-process reaper when PID 1 does not reap orphaned processes.

Qualification used SDK 10.0.400:

- Shared-provider analysis: **28 tests** on Bazel 8.8.0 and 9.2.0.
- Runner unit checks: **33 tests**, including dotnet/corerun environment isolation.
- Archive validation: **5 tests** on each Bazel version.
- Actual downloaded runtime and generated-host invalidation: macOS ARM64 and
  Linux ARM64, both Bazel versions. Offline reuse was checked with `--nofetch`;
  this does not claim a network-isolated build of arbitrary application dependencies.
- Source-built corerun/CoreLib smoke: Linux ARM64, Bazel 9.2.0. Runtime payload
  mutation reran and failed the test with **zero managed compilations**; restoring
  it recovered the passing cached test. This did not measure a CoreLib source-body
  edit or qualify the complete upstream runtime test suite.
