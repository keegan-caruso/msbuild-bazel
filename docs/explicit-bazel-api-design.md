# Explicit Bazel graph and generic MSBuild rules

Status: finalized design direction; APIs below are not implemented. This document
supersedes the application-wide discovery optimization as the next architectural
priority. Existing behavior and benchmark results remain unchanged.

## 1. Ownership

**Bazel owns the dependency graph, configuration, declared inputs, execution
platform, scheduling, and caching. MSBuild executes the declared project's SDK
and target behavior within that boundary.**

- BUILD files declare project and package edges before action execution.
- Sources, imported build logic, analyzers, generators, resources, and runtime
  files are explicit inputs. Globs in BUILD files are explicit declarations of
  file membership; arbitrary scans of the checkout during execution are not.
- Platforms, build settings, and `select()` express conditional choices.
- SDK tasks may transform declared inputs and generate intermediates inside the
  action's writable output area. They may not introduce hidden external inputs,
  restore dependencies, or recursively build referenced projects.
- No Orchard-specific rules, attributes, resource naming, or feature detection.
  Orchard's declared MSBuild targets retain their behavior, like any other
  project's targets.
- Ordinary builds do not run application-wide MSBuild graph discovery.

A `.csproj` is required initially for SDK/target behavior and IDE compatibility.
For Bazel builds, BUILD declarations are authoritative for graph and input
membership. Existing project declarations must agree with the selected Bazel
configuration; conflicting edges/options produce actionable errors. Merely
silencing ProjectReference or PackageReference processing is not a consistency
check. Validation uses the project evaluation already needed for execution,
without launching another whole-graph traversal.

An optional migration/sync tool can propose BUILD files from project files.
Changes are reviewed and checked in. It does not silently update the graph during
normal builds. Source-of-truth disagreements are resolved in declarations rather
than by choosing whichever graph the last command happened to evaluate.

## 2. Public rules

| Rule | Purpose |
| --- | --- |
| `msbuild_library` | Build one managed assembly with a reference/API output and runtime outputs |
| `msbuild_binary` | Build a runnable managed application and expose a launcher |
| `msbuild_test` | Build a runnable test application and expose a Bazel test launcher |
| `msbuild_items` | Associate declared files with an MSBuild item type and metadata |

The initial execution slice is managed .NET SDK projects. Generic naming does not
claim immediate support for every language, workload, native toolchain, or custom
MSBuild project. Additional SDKs retain the same explicit-input contract.

### Common project attributes

| Attribute | Contract |
| --- | --- |
| `project` | Label of one project file; required |
| `target_framework` | One explicit TFM for the configured target |
| `assembly_name` | Defaults to project filename stem, independent of Bazel target name |
| `srcs` | File labels mapped to `Compile`, including declared generated sources |
| `items` | Labels providing generic MSBuild item groups |
| `deps` | Direct assembly/package dependencies |
| `analyzers` | Analyzer/source-generator targets with their complete support-file closure |
| `framework_refs` | Framework names supplied by pinned targeting packs |
| `msbuild_imports` | Explicit imported files, retaining their logical project-relative layout |
| `build_deps` | Targets providing imported build logic, task assemblies, and supporting tools/files |
| `data` | Runtime/test inputs, never automatically compiler inputs |
| `data_paths` | Optional label-to-relative-destination mapping for singular data files |
| `defines`, `nullable`, `lang_version`, `allow_unsafe` | Typed local compiler settings |
| `msbuild_properties` | Explicit additional scalar properties, subject to reserved-property validation |

Use normal Bazel visibility, compatibility, tags, and executable/test attributes.
Bazel compilation mode maps to Debug/Release through a documented shared mapping;
custom configurations use explicit build settings. Analysis must pass the same
selected configuration to all relevant SDK actions.

`msbuild_properties` cannot override the dependency graph, SDK location, restore
behavior, hermeticity controls, output roots, or settings owned by typed
attributes. File-valued inputs cannot be hidden in scalar strings. Unsupported
file-valued task/property integration requires a typed file/tool binding before
it is admitted. There is no unrestricted `extra_inputs` or arbitrary MSBuild
command-line escape hatch.

`data` uses a deterministic runtime layout: files in the current Bazel package
retain package-relative paths; external data retains an unambiguous logical
location unless explicitly mapped. `data_paths` overrides must be relative,
collision-free, and cannot escape the runtime root. A declared generated tree
can represent larger layouts. Both the managed launcher and test launcher use
this same layout, so `xunit.runner.json` can sit beside the test assembly.

### Example assembly

```starlark
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_library", "msbuild_items")

msbuild_items(
    name = "embedded_assets",
    item_type = "EmbeddedResource",
    srcs = glob(["Views/**", "wwwroot/**"]),
)

msbuild_items(
    name = "razor_views",
    item_type = "RazorGenerate",
    srcs = glob(["Views/**/*.cshtml"]),
)

msbuild_library(
    name = "Catalog",
    project = "Catalog.csproj",
    target_framework = "net10.0",
    srcs = glob(["**/*.cs"], exclude = ["bin/**", "obj/**"]),
    items = [":embedded_assets", ":razor_views"],
    deps = ["//src/Common", "@nuget//newtonsoft.json"],
    analyzers = ["//tools/CatalogGenerator:analyzers"],
    framework_refs = ["Microsoft.AspNetCore.App"],
    msbuild_imports = ["//build:Catalog.props", "//build:Catalog.targets"],
    visibility = ["//visibility:public"],
)
```

The imported targets compute custom resource names, item transformations, and
assembly attributes. The rule does not implement those semantics itself. One
file may deliberately participate in multiple item types.

## 3. Generic items and imported logic

`msbuild_items` has `item_type`, `srcs`, and optional `metadata` attributes.
Metadata applies to the group's files; use another group for different metadata.
Bazel-configurable attributes may use `select()`.

```starlark
msbuild_items(
    name = "shared_resource",
    item_type = "EmbeddedResource",
    srcs = ["//shared:Messages.json"],
    metadata = {
        "Link": "Resources/Messages.json",
        "LogicalName": "Catalog.Resources.Messages.json",
    },
)
```

Other examples are `AdditionalFiles`, `EditorConfigFiles`, `Content`, and custom
item types consumed by declared targets. `Identity`/physical paths come from
Bazel File objects, not caller-controlled absolute paths. Item names and metadata
must be escaped for MSBuild correctly. Logical paths in `Link` are not physical
input paths. Custom metadata referencing additional physical files needs an
explicit file binding; scalar metadata is not a way around input declaration.

The runner supplies declared items at the appropriate SDK boundary and prevents
implicit SDK item globs from expanding the source universe. Imported targets can
transform items and add generated files inside the action. Implementation must
verify that the actual compiler/task inputs stay within declared input and
writable output roots. A sandbox enforces the filesystem boundary; XML inspection
alone is not a substitute.

`build_deps` carries build behavior independently of compile dependencies. A
package/project may supply both and be declared in both roles. Build targets
record import placement and tool bindings explicitly; tool executables use the
execution platform. Analyzer assemblies run in the compiler host and must be
compatible with that host, rather than blindly inheriting the application's RID.

## 4. Frameworks and conditions

One configured target produces one TFM. Initially use separate targets for
multiple TFMs, with a macro sharing common declarations. There is no automatic
cross-framework graph negotiation hidden in a build action. Reject incompatible
or ambiguous references; supported framework-compatibility rules belong in the
rule/toolchain contract. A netstandard dependency is not rejected merely for
having a different TFM.

```starlark
deps = ["//src/Common"] + select({
    "@platforms//os:windows": ["//src/WindowsIntegration"],
    "@platforms//os:linux": ["//src/LinuxIntegration"],
    "//conditions:default": [],
})
```

Feature flags and unusual conditions become explicit build settings or separate
targets. Conditions depending on undeclared host files or environment are not
supported. RID/native support uses declared target-platform selection and a
qualified toolchain mapping; it is not inferred from the machine running Bazel.
Automatic TFM transitions are deferred.

## 5. Packages and SDKs

Bzlmod extensions provide pinned SDK toolchains and locked NuGet repositories:

```starlark
dotnet = use_extension("@rules_msbuild//msbuild:extensions.bzl", "dotnet")
dotnet.sdk(name = "dotnet_sdk", version = "10.0.400")
use_repo(dotnet, "dotnet_sdk")
register_toolchains("@dotnet_sdk//:all")

nuget = use_extension("@rules_msbuild//msbuild:extensions.bzl", "nuget")
nuget.lock(name = "nuget", lock_file = "//:nuget.lock.json")
use_repo(nuget, "nuget")
```

SDK distributions have pinned content digests. Toolchain resolution handles
execution-platform selection; runtime and target packs follow the target's
explicit requirements. No machine-specific SDK paths in project BUILD files.

The checked-in NuGet lock describes exact versions, archive digests, sources,
dependency edges, and supported TFM/RID asset selections. A separate update tool
uses NuGet semantics to produce it. Normal builds do not resolve floating versions
or contact feeds from compilation/test actions. Repository fetching can obtain
locked archives using Bazel's repository mechanisms.

An archive is extracted/validated once by a cacheable package action. Its declared
files and metadata are authoritative downstream. Consumers do not reopen the
archive or independently requalify the entire payload. An extraction action's
output cannot invent new Bazel target edges during execution: those must already
be described by the lock and generated repository definitions.

Role labels are explicit:

- `@nuget//package.id`: locked compile/runtime assets and package dependency closure.
- `@nuget//package.id:analyzers`: analyzer/generator assets and support closure.
- `@nuget//package.id:build`: imported MSBuild logic and required tools/files.

Required build roles cannot silently activate through an ordinary `deps` entry.
Missing required roles fail with a message naming the declaration needed. Locked
transitive build behavior is represented through explicit build-provider edges.
Resolve package version conflicts during lock updates or reject incompatible
closures; never choose a winner based on traversal order.

## 6. Executable tests

**The baseline `msbuild_test` runs a managed executable, including MTP programs.**
It shares build/runtime construction with `msbuild_binary`, then registers a
Bazel test launcher instead of an ordinary run launcher.

```starlark
msbuild_test(
    name = "Catalog.Tests",
    project = "Catalog.Tests.csproj",
    target_framework = "net10.0",
    srcs = glob(["*.cs"]),
    deps = ["//src/Catalog", "@nuget//xunit.v3.mtp-v2"],
    build_deps = ["@nuget//xunit.v3.mtp-v2:build"],
    data = ["xunit.runner.json"],
    size = "small",
)
```

Package-role availability is generated from the selected lock; the example's
build label denotes its required MTP build integration, not an assertion that
all test packages have identical asset layouts.

At test execution the launcher runs the already-built application with the
pinned runtime, equivalent to `dotnet Catalog.Tests.dll`, with its `.deps.json`,
`.runtimeconfig.json`, runtime closure, configuration, and data. There is no
`dotnet test`, restore, project evaluation, solution enumeration, or implicit
build during test execution. No MTP/VSTest selection attribute is required for an
executable test. CLI runner selection in global.json is irrelevant to direct
execution, although that file remains a declared build input if consumed there.

The launcher:

- Preserves zero/nonzero exit status and propagates cancellation.
- Uses Bazel's runfiles and writable test directories; forwards test arguments.
- Lets Bazel own timeouts, scheduling, retries, and result caching.
- Does not silently ignore requested test filtering or sharding. Until supported,
  rejects unsupported requests and does not advertise sharding support.

Basic pass/fail and logs do not require a test-framework-specific integration.
Per-case XML, coverage, framework-specific filters, and sharding are additional
capabilities, requiring declared extensions or a bridge. Never claim a TRX file
is automatically Bazel-compatible XML. Tests that use external services need
explicit data/environment and appropriate Bazel execution/cache settings.

VSTest test libraries require a separate, explicit adapter with a pinned host and
adapter closure. Its public API is deferred; it does not complicate the baseline
executable-test rule.

## 7. Outputs and providers

Internally use typed providers with Bazel File objects and depsets:

| Provider | Carries |
| --- | --- |
| `MSBuildAssemblyInfo` | Assembly identity, TFM, reference/API output, implementation output, compile-reference closure |
| `MSBuildRuntimeInfo` | Runtime files, destinations, dependency/composition metadata |
| `MSBuildItemsInfo` | Item types, file labels, logical paths, metadata |
| `MSBuildAnalyzerInfo` | Analyzer/generator files and support closure |
| `MSBuildBuildInfo` | Import order/placement, task assemblies, files, tools |
| Toolchain provider | SDK, compiler, runtime, targeting packs, launchers |

Project declarations list direct edges. Provider propagation preserves the
qualified .NET transitive-reference semantics; direct-edge declaration does not
claim strict direct-only compiler references. Analyzer propagation is explicit.

Keep compile references separate from implementation/runtime outputs. Ordinary
consumer compilation should not depend on runtime-only changes when reference
bytes and all other compile inputs are unchanged. Analyzers and generators depend
on executable implementation bytes. Runtime composition consumes current runtime
outputs independently. SDK operations that genuinely consume implementation
metadata must declare that dependency rather than promise impossible reuse.

Expose normal assembly/default outputs and useful output groups for reference
assemblies, runtime content, and diagnostics. Large dynamic file sets may use
declared tree artifacts; prefer separate reference files where it improves cache
granularity. Do not repack every project into a `.nupkg` for internal dependencies.

## 8. Execution and cache boundary

Bazel action inputs include toolchain/runtime files, imported logic, project
configuration, item membership/metadata, package selections, and dependency
artifacts. Action environment and properties are explicit. Output-affecting
host state must be pinned, declared, or excluded.

Input declaration alone does not prevent undeclared reads or concurrent input
mutation. Qualify a filesystem boundary that exposes only declared inputs and
permits writes only to action outputs/scratch. Preserve that enforcement when
removing repeated adapter snapshots. Persistent workers must preserve request
isolation and compiler-cache correctness. Execution strategy is an implementation
choice, not a per-project API requirement.

Known declared graph → project-local SDK evaluation/build → declared outputs.
There is no public preparation target or application-wide plan requirement. A
project-local evaluation action can be separated if measurement demonstrates a
useful cache boundary; avoid extra actions that only serialize cheap operations.

## 9. Adoption and acceptance

Implement in independently reviewable stages:

1. Library → binary with explicit project edges, SDK toolchain, sources/imports,
   generic items, and Bazel run support.
2. Locked package outputs, explicit analyzer/build roles, generated sources, and
   reference/runtime separation.
3. Executable tests, including MTP, with no build activity during test execution.
4. SDK-specific behavior exercised through generic declared items/imports,
   including Orchard modules/themes and Razor; add migration tooling afterward.

Required acceptance evidence:

- Declared inputs suffice in a clean sandbox; undeclared reads and hidden edges fail.
- Conditional configurations build the expected different graphs and outputs.
- Producer-free remote-cache recovery reproduces accepted outputs.
- Source changes, added/removed glob members, shared imports, package changes,
  generator changes, and resource-only edits invalidate the correct actions.
- Dependency body-only changes preserve consumer compilation where reference
  identity and SDK semantics permit it; API changes rebuild affected consumers.
- MTP tests execute recovered binaries without restore, build, or project evaluation;
  failures propagate, runtime data paths work, and unsupported filters/shards fail.
- Orchard resource names, generated attributes, Razor behavior, and runtime assets
  match raw MSBuild for the qualified configuration. Independent-path Razor
  determinism remains a separate condition to prove, not an assumed result.
- Measure full cold build, unchanged remote hit, leaf edit, API edit, and resource
  edit against raw MSBuild with comparable settings. No speedup is claimed by
  this design document.

The earlier Orchard API sketch is superseded where it proposed Orchard-specific
resource helpers or mandatory MTP runner selection.

## References

- [Bazel rules, actions, and providers](https://bazel.build/extending/rules)
- [Bazel toolchains](https://bazel.build/extending/toolchains)
- [Bazel configurable attributes](https://bazel.build/configure/attributes)
- [Bazel test contract](https://bazel.build/reference/test-encyclopedia)
- [Direct execution of MTP applications](https://learn.microsoft.com/en-us/dotnet/core/testing/microsoft-testing-platform-run-and-debug)
