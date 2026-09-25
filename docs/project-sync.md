# Synchronizing projects into BUILD declarations

`ProjectSync` is an initial, local BUILD-file generator. It uses MSBuild evaluation
with an explicitly selected SDK; it does not parse project XML into guessed
property values. Ordinary Bazel builds do not invoke it.

## First slice

After `bash scripts/setup.sh`, point it at a separate application workspace:

```sh
bash /path/to/rules_msbuild/scripts/project-sync.sh /absolute/app-workspace App/App.csproj
bash /path/to/rules_msbuild/scripts/project-sync.sh /absolute/app-workspace App/App.csproj --check
```

Project arguments are workspace-relative. Supply the same entry projects for each
synchronization. Their transitive project references are included automatically.
The workspace must already have a `MODULE.bazel` declaring the rules dependency
and SDK toolchain; see [SDK setup](development.md). For this first slice use the
explicit SDK `version` form so no authored root BUILD file is needed.

The tool emits one root `BUILD.bazel`. For `Core/Core.csproj` it names the target
`Core_Core`; a library uses `msbuild_project` with explicit per-framework sources,
imports and dependencies. A single-framework console app uses `msbuild_binary`.
For example, the generated app can be run with `bazel run //:App_App`.

Generation is deterministic and owns the entire root BUILD file. It refuses to
overwrite an authored BUILD file or cross an existing nested Bazel package.
Evaluation or validation failures leave existing output untouched. `--check`
evaluates the same inputs and exits nonzero if the declaration is missing or stale,
without writing it. This is a synchronization tool, not an editor for authored
BUILD files yet.

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
MSBuild globs are detected by `--check`; generated BUILD files list those files
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
matrices, and a `bazel run //:sync` or Gazelle entry point remain follow-up work.
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
and protection of authored BUILD files. The acceptance fixture builds and runs a
library/application graph, then changes an imported compiler property and verifies
the changed runtime output without regenerating the graph.

Qualified on macOS ARM64 with SDK 10.0.400 and **Bazel 8.8.0 and 9.2.0**:
the generated app prints `value=7`, then `value=9` after the imported-props edit.
The fixture also gives the project a conflicting default `Platform=x64`; emitted
`msbuild_properties = {"Platform": "AnyCPU"}` preserves the evaluation's selected
configuration during compilation. Both runs use the native macOS sandbox.
Seven generator controls, all existing owned-tool checks (including 35 runner
unit tests), and scaffold/Starlark checks pass. GitHub CI was not dispatched.
