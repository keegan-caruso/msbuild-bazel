# MSBuild / Bazel spike

## Question

Can Bazel cache and schedule configured .NET projects while each action uses MSBuild and consumes dependency artifacts plus MSBuild result metadata?

## Planned sequence

1. Add Shared and App SDK projects, with App referencing Shared, and a Microsoft.Build.Traversal entry point. Pin Traversal when introduced.
2. Establish a normal Release traversal/static-graph build baseline and confirm project isolation.
3. Build Shared separately; stage its artifacts and result cache; build App with the input result cache. Verify Shared compilation does not execute again.
4. Repeat with clean directories and changed checkout/action paths. Investigate absolute paths in result metadata before claiming portable caching.
5. Prove relocated dependency-result replay through public MSBuild project-cache APIs, using a versioned metadata payload and separately staged artifacts. Keep the raw-cache path probe as a control. See the [replay experiment](result-replay-plan.md) for the proposed contract and acceptance cases.
6. After replay works, define the Bazel e2e harness and add a custom rule and runner for these two explicit targets. Keep restore/tool acquisition outside compilation actions; test separate action paths and sandbox inputs explicitly.
7. Measure cold build, unchanged rebuild, App-only edit, Shared edit, and reuse after clearing local outputs while retaining the Bazel disk cache. Assert which actions execute and verify application output.
8. Only after the handoff works, add a general C# ProjectGraph exporter and custom MSBuild targets for input/output contracts. The replay experiment may use ProjectGraph for the two-project fixture without expanding into a general exporter.

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

Codex setup and CI are established. The initial process contract and six e2e scenarios were committed before implementation. See [e2e scope](e2e-scope.md), [interfaces](interfaces.md), and [findings](findings.md).

Step 4 now has a runnable path probe and a seventh e2e test. On macOS ARM64 with
the pinned Nix SDK, moving the bundle preserves App-only compilation, but moving
the project workspace causes raw MSBuild `MSB4252` at `GetTargetFrameworks`. A
fresh dependency cache at the new path succeeds. See [path findings](path-findings.md)
for commands, controls, and limitations. The next step is the
[public-API result-replay experiment](result-replay-plan.md), before implementing
the two-target Bazel rule. Test whether normalized target-result metadata can
replace the raw cache at a changed workspace path before investing in fixed
absolute paths or an MSBuild fork. Neither replay nor sandbox/remote-cache
portability has been established.
