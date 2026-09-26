# Synchronizing projects into BUILD declarations

`ProjectSync` is an initial, local BUILD-file generator. It uses MSBuild evaluation
with an explicitly selected SDK; it does not parse project XML into guessed
property values. Ordinary Bazel builds do not invoke it.

## App developer setup

Declare `rules_msbuild` and its SDK toolchain in `MODULE.bazel` as described in
[SDK setup](development.md). No local .NET installation or rules checkout is
needed to run synchronization; Bazel builds the generator from the dependency's
sources using the registered SDK.

Start with this root `BUILD.bazel`:

```starlark
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")

msbuild_sync(
    name = "sync",
    projects = ["src/App/App.csproj"],
)
```

Run once to create the generated file:

```sh
bazel run //:sync
```

Then add the generated macro to your root BUILD file:

```starlark
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")
load(":projects.generated.bzl", "app_projects")

msbuild_sync(
    name = "sync",
    projects = ["src/App/App.csproj"],
)

app_projects()
```

```sh
bazel build //:src_App_App
bazel run //:src_App_App
bazel run //:sync -- --check
```

Do not load `projects.generated.bzl` before the first sync has created it. Commit
that file alongside the authored BUILD file. Later `bazel run //:sync` updates
only the generated file; `--check` fails on drift without changing either file.
The target name derives from the workspace-relative project path with directory
separators replaced by underscores. Referenced projects are included recursively.

The sync target belongs in the workspace root and generates declarations for that
one Bazel package. It refuses to cross existing nested packages or overwrite an
authored `projects.generated.bzl`. Evaluation and validation failures preserve
existing output. The generated `app_projects()` must also be called from the root.

Project paths are strings rather than labels: sync deliberately evaluates the
current checkout at **run time**, using `BUILD_WORKSPACE_DIRECTORY`. It can find
new source files and imports without first declaring them as inputs to itself.
The generator bootstrap and declared input producers are cached build actions. Project evaluation and
writes are explicit local developer operations, never remote build actions.
Use a host-compatible SDK execution platform for this local tool; cross-platform
execution configurations are not qualified.

The repository's `scripts/project-sync.sh` remains a maintainer convenience for
running the same generator directly. It is not required by application users.

## What evaluation resolves

- `Directory.Build.props`, property-only `Directory.Build.targets`, and nested
  explicit imports, retained as workspace-relative `msbuild_imports` inputs.
- Property expansion, target framework lists, and conditional source inclusion
  and exclusion for each evaluated framework.
- Project references and recursively generated library dependencies.
- Nullable, language version, unsafe-code and apphost settings.

The current evaluation is **Release / AnyCPU on the host running the tool**.
It does not enumerate operating systems, arbitrary property combinations, or
translate arbitrary conditions into `select()`. Environment-dependent conditions
remain a limitation: the result describes the chosen local evaluation, not every
possible configuration. Use the same SDK/configuration when syncing and building.
SDK imports are supplied by the Bazel toolchain rather than emitted as local paths.
Workload resolution is disabled. Generated NuGet extension props/targets under
`obj` are not imported; there is no restore or build-target execution during sync.

A props edit that changes only compiler behavior can leave the generated graph
unchanged: Bazel already tracks that imported file. Changes to evaluated sources,
frameworks, imports or dependencies require synchronization. New files matched by
MSBuild globs are detected by `--check`; generated declarations list those files
explicitly rather than approximating MSBuild globs with Bazel globs.

## Explicit package and test mappings

Add a JSON label to the sync macro:

```starlark
msbuild_sync(
    name = "sync",
    projects = ["tests/CoreTests/CoreTests.csproj"],
    mappings = "sync.json",
)
```

For example, `sync.json` can contain:

```json
{
  "packages": {
    "xunit/2.9.3": {
      "label": "//packages:xunit",
      "roles": ["deps", "build_deps"]
    }
  },
  "tests": {
    "tests/CoreTests/CoreTests.csproj": {
      "protocol": "vstest",
      "runner": "//test_tools:tools_runner",
      "adapters": ["//test_tools:tools_xunit"]
    }
  }
}
```

Declare all of the project's direct package references, not just the illustrative
one above. Package keys are exact evaluated `ID/version` pairs (case-insensitive).
Each label points to an already declared, checksum-locked package dependency
closure. `roles` explicitly selects `deps`, `build_deps`, and/or `analyzers`.
An optional `analyzers` label list adds analyzer bindings from the declared closure.
Centrally declared `PackageVersion` items are evaluated and matched too; sync
records the imported `Directory.Packages.props` as a build input.

Sync does not resolve NuGet versions, download packages, inspect their archives,
or infer asset roles. Different resolved dependency closures still require the
appropriate authored package targets. A missing exact mapping or unsupported
PackageReference metadata fails before output changes. A package mapping table
can contain entries unused by a particular selected project graph.

Test keys are exact workspace-relative project paths. `protocol` is required:
`vstest`, `mtp`, or `executable`. Only VSTest accepts `runner` and `adapters`.
Mapped projects generate `msbuild_test_project` declarations. An evaluated test
project without a mapping is rejected, as is a test mapping outside the reachable
graph. Explicit mappings can also mark an ordinary executable as a test.

Optional test fields are `outputType` (`exe`/`library`), `settings`,
`workingDirectory`, `outputDirectories`, `filterArgument`, `dataPaths`,
`environment`, and `properties`. These map to the existing test rule attributes;
file/label values are relative to the generated root package. Test properties
and output type are applied during evaluation as well as emitted for compilation.
Reserved evaluation properties cannot override Release/AnyCPU or framework
selection. For MTP, explicitly declare its TRX reporting package/build role.
Unknown mapping fields and invalid protocol/runner combinations fail explicitly.

## Selecting a repository slice

Use `projects` in the same mappings file for per-project configuration:

```json
{
  "projects": {
    "src/Core/Core.csproj": {
      "targetFrameworks": ["net10.0"],
      "properties": {"Flavor": "portable"}
    }
  }
}
```

The framework list selects a subset of the **evaluated declared frameworks**;
unknown frameworks fail. Omitting it keeps every declared framework. Properties
are applied both during evaluation and in the generated `msbuild_properties`.
They are local to that project, not silently propagated through its dependency
graph. Give dependencies their own mappings where needed. Project and test
properties combine; conflicting values fail. Reserved configuration/framework
properties still cannot be overridden through the property dictionary. Stale or
unreachable project mappings fail before writing output.

`Compile` inputs can carry `Link` and `LinkBase`. Existing `EmbeddedResource`,
`AdditionalFiles`, `Content` and copied `None` inputs emit `msbuild_items` with
explicit file labels. Supported metadata is `Link`, `LinkBase`, `LogicalName`,
`ManifestResourceName`, `Culture`, `WithCulture`, `CopyToOutputDirectory`,
`CopyToPublishDirectory` and `TargetPath`. Source items retain only Link/LinkBase.
Metadata requiring generation, such as `GenerateSource`, is rejected. Missing
files still require a generator binding; sync never runs a generation target.
Ordinary uncopied `None` files remain outside build inputs.

Package `PrivateAssets` accepts NuGet asset masks, including partial masks.
`IncludeAssets`, `ExcludeAssets` and central `VersionOverride` remain in the
original project. An override must match an exact package binding and is rejected
when `CentralPackageVersionOverrideEnabled=false`. Unknown asset names fail.
Dependency restore records preserve package edges and their asset metadata rather
than promoting inherited packages into direct references. Boolean
`IsImplicitlyDefined` and `GeneratePathProperty` are retained too. Exact package
version/role bindings are still mandatory.

See the [ASP.NET Core/runtime inventory](project-sync-upstream.md) for concrete
remaining integration gates and synthetic validation commands.

## Bootstrap, reference and task bindings

For generated imports/sources/resources and NuGet SDKs:

```starlark
msbuild_sync(
    name = "sync",
    projects = ["src/App/App.csproj"],
    mappings = "sync.json",
    inputs = {
        ":generated_props": "artifacts/generated.props",
        ":generated_source": "artifacts/Generated.cs",
    },
    package_lock = ":repository_packages",
    bindings = [":build_tasks_path"],
)
```

Each `inputs` label supplies exactly one file. For `msbuild_generate` with several
outputs, select each file using a `filegroup(output_group = "relative/output")`.
Bazel builds these producers before synchronization. A temporary evaluation view
places the files at their logical paths without writing into the source checkout.
Generated declarations retain the producer labels in `source_paths`, `import_paths`
or `msbuild_items(paths = {...})`; they never contain temporary evaluation paths.
Missing producers, source collisions and unsafe paths fail.

`package_lock` supplies the complete declared NuGet package set, including imported
SDKs. The view clears package feeds/fallback folders and uses only those package
directories. A missing SDK fails instead of downloading it. The `msbuild-sdks`
section of `global.json` is accepted by SDK acquisition, but its packages must be
bound separately; it is not a download instruction. Repository-specific global.json
fields beyond the supported SDK fields still require explicit SDK version setup.
The direct maintainer CLI without an input manifest retains its original local
filesystem evaluation behavior.

Per-project mappings can declare:

| Field | Meaning |
| --- | --- |
| `references` | Bare assembly identity → `{ "role": "compile"/"package"/"framework", "label": ":producer" }`; framework uses the declared assembly identity |
| `projectReferences` | Workspace-relative project path → role and label; roles are `compile`, `private`, `analyzer`, `tool`, `output` |
| `tools`, `bindings`, `items`, `adapterImports` | Authored labels for existing rule primitives |
| `outputMode` | `sdk`, `reference` or `implementation` |
| `referencePack`, `runtimeHost` | Explicit existing reference-pack/runtime providers |
| `directories`, `layoutBindings` | Existing logical-directory and layout-property contracts |
| `documents` | Reviewed contracts for imported/project XML containing targets/tasks |
| `evaluationItems` | Explicit item kinds used as repository bookkeeping; this does **not** declare file inputs |

A mapped project edge uses its authored label. It does not recursively generate
that producer; include the producer among `projects` if it should also be synced.
Unmapped ordinary project edges retain recursive generation. Role/metadata
mismatches fail. A private dependency controls propagation; selecting an
implementation assembly is a separate decision. `SkipUseReferenceAssembly=true`
requires an explicitly selected implementation-reference producer.

Custom document contracts name the exact SHA-256, target names, task names and
additional input files:

```json
{
  "projects": {
    "src/App/App.csproj": {
      "tools": [":build_tasks"],
      "bindings": [":build_tasks_path"],
      "documents": {
        "eng/Generate.targets": {
          "sha256": "<sha256 of the reviewed file>",
          "targets": ["Generate"],
          "tasks": ["Example.GenerateTask"],
          "inputs": ["eng/generation-input.txt"]
        }
      }
    }
  }
}
```

The corresponding `msbuild_file_binding` must also appear in the sync rule's
`bindings` so evaluation sees the declared managed tool. Sync runs no task.
Package task documents use paths under `.nuget/packages/<id>/<version>/...`.
Changed hashes/target lists/task lists and stale document paths fail. These are
**authored completeness contracts**, not a proof that arbitrary target code is
hermetic. Declare all files/tools/layouts that those targets consume. Property
functions expecting a merged tool-directory layout are not qualified.

SDK `InternalsVisibleTo` declarations are retained. `AssemblyOriginatorKeyFile`
is a required tracked input even when it is an uncopied `None` file. The synthetic suite checks signed friends and wrong-key rejection; signed upstream
builds are not yet qualified.

## Explicit limits

The generator accepts `Microsoft.NET.Sdk` libraries, single-framework console
applications, and explicitly mapped tests/packages. Custom targets/tasks and
repository item kinds need the contracts above. Explicit user `Analyzer` and
`FrameworkReference` items still need further integration; normal SDK analyzers
and the implicit .NET Core framework are retained. Bare assembly bindings are
separate from framework-reference resolution. Imports outside the workspace,
selected SDK or closed package set fail.

Multi-framework applications, existing per-project BUILD packages, arbitrary
SDKs/workloads, cross-platform configuration matrices and Gazelle integration
remain follow-up work. Environment-dependent evaluation and absolute-path
property functions remain limitations of local synchronization. No remote-cache
or large-repository qualification is claimed for the new generator contracts.
See [blocker qualification](project-sync-bindings.md) for measured coverage.

## Validation

```sh
bash scripts/check-dotnet.sh
source scripts/env.sh
python3 tests/project_sync/acceptance.py /tmp/fresh-project-sync
```

The black-box controls cover nested props/targets imports, transitive references,
framework-specific source removal, stale declarations after props/source changes,
rejected unsupported inputs, cycles, generated restore imports, missing sources,
and protection of authored BUILD files. The acceptance fixture uses only
`bazel run //:sync` to bootstrap the generator and SDK, preserves the authored
BUILD file, builds and runs the generated graph,
checks imported compiler-property edits, and detects/resynchronizes new sources.
It removes local dotnet configuration and SDK directories from PATH.

Qualified on macOS ARM64 with SDK 10.0.400 and **Bazel 8.8.0 and 9.2.0**:
the generated app prints `value=7`, then `value=9` after the imported-props edit.
The fixture also gives the project a conflicting default `Platform=x64`; emitted
`msbuild_properties = {"Platform": "AnyCPU"}` preserves the evaluation's selected
configuration during compilation. Both runs use the native macOS sandbox.
Twelve generator controls, all existing owned-tool checks (including 35 runner
unit tests), and scaffold/Starlark checks pass. GitHub CI was not dispatched.

## Fixture simplification

`tests/support/vstest.bzl` supplies `vstest_tools`: one runner and a dictionary of
named adapter package/path bindings. It is test support, not a new public rule
API. The VSTest and upstream-suite preparation scripts share these declarations.

- `python3 tests/project_sync/hello.py /tmp/fresh-hello` exercises the existing
  hello library/app sources using generated declarations and an executable test.
  `examples/hello/create.py --sync` selects this preparation mode; the original
  handwritten example remains available as an independent comparison.
- `python3 tests/explicit_msbuild/vstest.py /tmp/fresh-vstest --sync` migrates the
  existing xUnit/NUnit/MSTest fixture through package/test mappings. It retains
  passing, filtered, intentional-failure, empty-selection and retained-output
  assertions. Omitting `--sync` retains its handwritten Linux-worker path.
- `python3 tests/project_sync/mapped_protocols.py /tmp/fresh-mtp` reuses the MTP
  fixture sources with package/test mappings and checks pass/failure/restoration.

Source setup and package locking remain fixture preparation. The low-level
handwritten rule/declaration rejection tests are not routed through sync.

The [fixture evidence](project-sync-fixtures-evidence.json) records all 12 VSTest
cases passing their expected contracts on Bazel 8.8.0 and 9.2.0, and the three
MTP pass/failure/restoration cases on 9.2.0. These checks ran on macOS ARM64.
The upstream Serilog/Spectre preparation now uses the shared macro; their full
suites were not rerun for this declaration-only refactor.
