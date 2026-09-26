# Explicit Bazel rule API

The rule implementation is in
`msbuild/defs.bzl`, with a .NET host in `tools/ExplicitBuild`. This is the active build
interface; the older preparation/discovery shell entry points are retired. Full Orchard
CMS qualification and raw MSBuild measurements are documented in
[the Orchard benchmark](orchard-explicit-performance.md).

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
- Runtime trees contain project outputs and manifests describing SDK-selected
  package files. Package files stay in declared extraction artifacts; launchers,
  analyzers and task bindings compose them on demand. A runtime tree alone is
  not a deployable directory: use the Bazel launcher or consume the provider's
  runtime package closure. SDK build targets still see their normal copied output
  files before publication. Application package-version precedence and collision
  checks remain enforced.
- Package extraction declares the .NET host/runtime instead of the entire SDK;
  compilation retains the full SDK and platform runtime closure.
- A toolchain supplies the SDK, runner and runtime closure. BUILD attributes accept
  ordinary Bazel `select()` configuration. Project edges must select compatible
  target frameworks; tools use the execution platform's SDK/apphost.
- `msbuild_nuget_package` extracts each locked archive once as a Bazel action.
  Its transitive package closure is explicit. Archive SHA-256 and NuGet restore
  content hashes are separate inputs because signed archives can have different
  byte hashes from NuGet's lock content hash. Identity and extraction paths are
  checked. Project actions use read-only package trees without re-extracting them.
- `msbuild_nuget_dependencies(package = ..., deps = [...])` attaches a resolved
  dependency closure to a canonical extraction target without re-extracting its
  archive. This supports different framework-dependent closures for one archive.
- `msbuild_package_lock(packages = [...])` supplies an explicit resolved package set
  through an assembly's `package_lock` attribute. Direct package closures must agree
  with it; inherited versions are replaced by that consumer-selected set. Without
  a lock, inherited conflicts still fail. NuGet resolution happens outside these
  rules; the lock is an input, not a dependency solver.
- `framework_refs` propagate through project dependencies. `directories` declares
  empty logical workspace-relative directories required by original targets.
  Resource/content paths remain relative to their project so `RelativeDir` metadata
  works. Compiler additional files and analyzer configuration use absolute sandbox paths.
- `deps` enables compile/runtime package assets; `build_deps` and `analyzers` enable
  their respective roles. A package can be named in multiple attributes. Declaring
  a package closure makes its archives available; it does not promote every
  transitive dependency to a direct PackageReference. NuGet asset filters still apply.
- Each compiled project exports its SDK-selected NuGet identity as a separate small
  Bazel artifact. Consumers supply these records to restore without evaluating
  dependency projects. This preserves project-over-package resolution and project
  identities in generated runtime dependency files. Restore identities distinguish
  project path, implementation target framework and public compatibility framework,
  including transitive configurations and paired/direct views of the same project;
  conflicting metadata for the same identity is rejected. A paired
  `msbuild_assembly` supplies its contract framework for compiler and restore
  compatibility, retaining the implementation project identity and dependency
  graph. Configured-reference checks still use the implementation framework.
  Implementation-only dependencies remain runtime-only inputs to executable
  dependency manifests; pairing does not expose their APIs to the compiler.
  Unpaired platform-incompatible references are rejected.
- `msbuild_assembly(use_implementation_reference = True)` explicitly selects the
  implementation compiler reference while retaining the contract framework for
  compatibility and checking both assembly identities. This supports friend APIs
  and projects that deliberately compile against implementation metadata. It
  exposes implementation APIs and makes implementation-body changes invalidate
  consumers when the implementation PE is their reference; the default public
  contract preserves the narrower compile dependency.
- NuGet SDKs are supplied through `package_lock` and a declared `global.json`.
  SDK resolution uses the same read-only package tree as restore.
- `framework_assemblies` declares bare framework Reference names, validated against
  the selected SDK or locked reference pack. Alias and path overrides are rejected.
- `package_reference_paths = {"Package.Id": ["ref/net10.0/Assembly.dll"]}`
  declares exact DLLs within an already locked package. Each must match one
  evaluated absolute `Reference` path; missing files, undeclared packages,
  duplicates, aliases and path overrides fail. Original metadata such as
  `Private=false` remains effective. This does not add a PackageReference or
  infer a package's dependencies.
- `msbuild_project_output(assembly = ..., item_type = "Content", metadata = {...})`
  supplies an implementation DLL through `project_outputs`, separately from compile
  references. `artifact = "reference"` selects the producer's reference DLL instead.
  Custom item names are supported; dependency/source item names and reserved
  `_Bazel` names are rejected. The role and copy metadata must match the original
  `ProjectReference`. This also supports reference-only producers without publishing
  a runtime DLL.
- `use_apphost = False` builds a managed executable without requesting a native
  apphost. The default remains `True`; the Bazel launcher can run either form.

A closed, single-project `Restore` still generates SDK/NuGet assets inside each
assembly action. It uses only declared packages and an empty feed list, with
network access denied. Removing this remaining per-project work is a future
optimization, not a result claimed here.

## Project facade

`msbuild_project` declares library variants and an aggregate target. Dependencies
can name the aggregate; the consumer selects one framework during Bazel analysis.
Sources, imports, packages and framework-dependent conditions remain explicit.

```starlark
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_project")

msbuild_project(
    name = "Core",
    project = "Core.csproj",
    target_frameworks = ["netstandard2.1", "net10.0"],
    srcs = ["Common.cs"],
    deps = [":Utilities"],
    framework_overrides = {
        "netstandard2.1": {"package_lock": ":standard_lock"},
        "net10.0": {"srcs": ["Modern.cs"], "deps": [":ModernDependency"]},
    },
)
```

This generates `:Core_netstandard2_1`, `:Core_net10_0`, and `:Core`. Variant names
replace dots in the TFM with underscores; other characters are retained. Building
`:Core` builds every variant. Using `deps = [":Core"]` builds only the selected
variant and its action dependencies. `MSBuildProjectInfo.variants` exposes a
TFM-to-`MSBuildAssemblyInfo` map to rule authors.

Selection prefers an exact TFM, then the highest compatible version in the same
family, then .NET Standard for modern .NET. Automatic fallback covers plain
`net5.0` and newer and `netstandard1.0`–`netstandard2.1`. Platform-qualified,
legacy and other TFMs require an exact match or an explicit variant label;
the existing SDK compatibility checks still apply to explicit edges. Framework
selection does not choose an execution runtime or change roll-forward policy.

`target_frameworks` and override keys must be literal, distinct declarations.
Common attributes accept ordinary `select()` values. Overrides extend list
attributes such as `srcs`, `deps`, `defines` and `data`; scalar and dictionary
attributes replace the common value. In particular, a property dictionary is
replaced, not merged. Override keys must name declared frameworks and cannot
change project identity or visibility. Package locks and reference packs remain
declared inputs; the facade does not acquire them or evaluate `.csproj` files.

Only `deps` selects a project facade. Tools, analyzers, paired assemblies and
project-output bindings should name explicit variants. Different configurations
of the same TFM use separate facade declarations or explicit rules. The facade
does not automatically resolve conflicting implementations where graph branches
meet. Use the explicit selection below when those variants share an assembly
identity.

All exposed variants are analyzed, including their dependencies, so each must
have a valid declaration. Direct variant labels avoid that additional analysis.
See the [200-project measurement](performance.md#project-facade-analysis).

## Private project compiler dependencies

Use `implementation_deps` for a project reference with `PrivateAssets="all"`.
These dependencies are available to the declaring project's compiler but their
references and compile packages are not exported through that edge. Their runtime
closure remains available, matching the SDK's project build behavior. All normal
inputs, configuration checks and action dependencies still apply. The fixture
inventory emits this attribute from resolved project-reference metadata.

Use `deps` for public project references; its evaluated `PrivateAssets` must be
absent or `none`. A mismatch fails during validation. Partial asset lists are not
supported by this project-dependency contract. Package visibility continues to
use `package_private_assets`.

## Configured branches and assembly selection

A helper can compile against `Core/netstandard2.1` while an application uses
`Core/net10.0`. Keep both configured producers and their original compilation
edges. At the convergence point, declare the implementation that the consumer
will compile and run against:

```starlark
msbuild_library(
    name = "Helper",
    project = "Helper.csproj",
    target_framework = "netstandard2.1",
    deps = [":Core_netstandard2_1"],
)
msbuild_binary(
    name = "App",
    project = "App.csproj",
    target_framework = "net10.0",
    deps = [":Core_net10_0", ":Helper"],
    assembly_selections = [":Core_net10_0"],
)
```

`assembly_selections` accepts explicit assembly variants, including paired
assemblies. It replaces competing compiler references and runtime artifacts at
that consumer and propagates the choice to downstream consumers. It leaves the
helper's own compilation unchanged. Restore metadata retains framework-specific
edges under the selected project identity, so the application's dependency
manifest describes the selected runtime assembly.

A selection must already occur in the active dependency closure, come from the
same project, and agree with direct `deps`. Conflicting inherited choices require
an explicit choice at their convergence point. Full assembly identity (name,
version, culture and public key token) and NuGet project name/version must match.
Reference-only dependency contracts carried by paired assemblies remain subject
to identity validation, but are not competing runtime projects when their runtime
artifacts are absent from the active closure.
Different global properties and configurations remain distinct restore nodes,
even when their TFMs match. Without a selection, conflicting artifacts retain the
existing collision checks.

This is an explicit compatibility assertion, not an API-superset check. Validate
that the selected implementation supports the APIs used by every branch. The
selection does not prune variant-specific package, data or descendant closures;
those retain their existing conflict checks. It is not automatic MSBuild assembly
conflict resolution. See [configured graph qualification](configured-graphs.md)
for raw parity, edit and recovery controls.

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

`msbuild_test` defaults to executable application tests. Select `test_protocol =
"mtp"` for per-test reporting and MTP filtering, or `"vstest"` with explicitly
bound runner and adapter packages for library-style test assemblies. Execution
never invokes restore, project evaluation, or compilation. See the
[Bazel test contract and qualification](bazel-test.md) for settings, XML/TRX,
cache behavior, empty-suite policy, and current sharding/coverage limits.

## Local toolchain setup and reproduction

Use the repository's pinned SDK 10.0.400 and Bazel 9.2.0. Set
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

The opt-in [Linux persistent worker](explicit-linux-workers.md) now reuses
MSBuild and Roslyn while retaining a read-only input boundary.

The compile child uses `sandbox-exec` on macOS and `bubblewrap` on Linux. The
parent stages declared files outside Bazel's sandbox to avoid nested macOS
sandboxing. Project actions can opt into [Linux remote execution](remote-execution.md)
with `allow_remote_execution = True`; the default remains local. The OS runtime is still part of
the supported environment: macOS system libraries/shell and Linux `/usr/lib` and
selected `/etc` files are exposed. A fully pinned remote execution image/platform
contract is still required; this is not a universal hermetic toolchain claim.

The project boundary is one C# SDK-style project with one root `Sdk` attribute,
one explicitly selected TFM per project dependency, NuGet-compatible compile
references, and framework-dependent output. See [framework/tool roles](framework-tool-roles.md).
Unsupported project-reference metadata and package metadata are rejected instead
of silently reinterpreted. Partial PrivateAssets masks,
arbitrary project-built MSBuild tasks, external-repository project-relative paths,
Windows, cross-compilation and publish/AOT remain unqualified. Declared task tools
use [explicit bindings](explicit-tool-bindings.md). Executable, MTP and VSTest
protocols are covered by the [test API](bazel-test.md). Scalar MSBuild properties cannot override reserved paths or graph
controls. Generated files should be declared labels; SDK-generated compilation
items can still be created inside the action.

The full Orchard CMS graph now has startup, embedded-asset and timing evidence in
[the Orchard benchmark](orchard-explicit-performance.md). Pinned SDK/lock extensions,
publish qualification and the design's larger performance goal remain open.

The opt-in [shared restore input](explicit-restore-inputs.md) now removes per-project
Restore from qualified plain package-free SDK projects. The general lane retains
per-project Restore.

[Central versions and private package declarations](orchard-package-semantics.md)
are qualified with locked packages, original NuGet metadata, and Linux controls.

[Project-built analyzers](project-built-analyzers.md) can be listed in `analyzers`;
their implementation closure is isolated from application compile/runtime deps.

[Explicit target-result items](msbuild-target-items.md) expose `export_targets` and
`msbuild_target_items` for declared scalar metadata edges between assembly builds.

## Runtime repository inputs

See [runtime primitives](runtime-primitives.md) for separate contract/implementation
assemblies, explicit producer configurations, locally built reference packs,
runtime-under-test selection, generated layouts and native tool bindings.

### Direct-only compilation references

`transitive_compile_references = False` on a library supplies
only the explicitly listed assembly dependencies to the compiler. The default
is `True`. Use this when the upstream project deliberately declares a complete
direct reference set; any additionally required assembly must be listed in
`deps`. Exported references and runtime dependencies retain their full transitive closure
for downstream applications. Binaries/tests reject this option: omitting their
transitive references can omit entries from the SDK runtime dependency manifest. This
option does not change package asset selection or resolve conflicting direct
assembly identities. See `tests/explicit_msbuild/direct_references.py`.

## Authored reference identities and generated file paths

`reference_projects = {":core": "Core"}` binds an exact bare MSBuild `Reference`
identity to a project provider. The provider assembly name must match. This is an
explicit public compile/runtime dependency, not assembly discovery. Existing
`reference_packages` and `framework_assemblies` serve package/framework identities.

`source_paths = {":generated": "src/Generated.cs"}` stages a single-file producer
at an explicit project-relative-to-workspace logical path. `msbuild_items` accepts
the same mapping as `paths` for generated resources/content. `import_paths` retains
its existing role for generated imports. These mappings are emitted by
[project synchronization](project-sync.md) when it consumes declared producers.
