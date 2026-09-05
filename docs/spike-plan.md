# MSBuild / Bazel spike

## Question

Can Bazel cache and schedule configured .NET projects while each action uses MSBuild and consumes dependency artifacts plus MSBuild result metadata?

## Planned sequence

1. Add Shared and App SDK projects, with App referencing Shared, and a Microsoft.Build.Traversal entry point. Pin Traversal when introduced.
2. Establish a normal Release traversal/static-graph build baseline and confirm project isolation.
3. Build Shared separately; stage its artifacts and result cache; build App with the input result cache. Verify Shared compilation does not execute again.
4. Repeat with clean directories and changed checkout/action paths. Investigate absolute paths in result metadata before claiming portable caching.
5. Add a custom Bazel rule and runner for these two explicit targets. Keep restore/tool acquisition outside compilation actions.
6. Measure cold build, unchanged rebuild, App-only edit, Shared edit, and reuse after clearing local outputs while retaining the Bazel disk cache. Assert which actions execute and verify application output.
7. Only after the handoff works, add a C# ProjectGraph exporter and custom MSBuild targets for input/output contracts.

## Acceptance evidence

- Plain MSBuild and Bazel-built App have equivalent observable output.
- App-only changes reuse Shared's Bazel action output.
- Shared changes invalidate dependent work correctly.
- Dependency builds are not silently repeated inside downstream actions.
- Results do not depend on pre-existing bin/obj or an undeclared user NuGet cache.
- SDK, package assets, configuration, imports, and custom inputs participate in action identity.

## Initial boundaries

Linux x86-64, one framework, Release, local execution and local disk cache. Remote execution, cross-platform support, multi-targeting, Native AOT, publishing, Razor/WPF, and arbitrary NuGet build targets need separate evidence. Pinned bootstrap tools alone do not make build actions hermetic.

## Recorded results

Environment scaffold only. The integration experiments above have not run.
