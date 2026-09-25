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
Only the generator bootstrap is a cached build action. Project evaluation and
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

## Explicit limits

This first slice accepts package-free `Microsoft.NET.Sdk` libraries and
single-framework console applications. It rejects package references, test
projects, custom targets/tasks, custom items, resources/content, user analyzers,
explicit framework/assembly references, special project-reference metadata and
missing/generated sources. These require mappings that the tool does not yet
provide. Normal SDK analyzers and the implicit .NET Core framework are retained.
Imports outside the workspace or SDK also fail explicitly.

Central package properties can be evaluated, but package resolution and package
BUILD declarations are not implemented. Multi-framework applications, existing
per-project BUILD packages, arbitrary SDKs/workloads, cross-platform configuration
matrices, and a Gazelle integration remain follow-up work.
No Linux, remote-cache, or large-repository qualification is claimed for this tool.

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
Seven generator controls, all existing owned-tool checks (including 35 runner
unit tests), and scaffold/Starlark checks pass. GitHub CI was not dispatched.
