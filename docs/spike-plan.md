# MSBuild / Bazel spike

## Question

Can Bazel cache and schedule configured .NET projects while each action uses MSBuild and consumes dependency artifacts plus MSBuild result metadata?

## Current status and next step

Steps 1–7 below are implemented. The two-target Bazel adapter also has
[action-identity](action-identity-findings.md) and
[pinned build-package](package-input-findings.md) acceptance coverage on macOS
ARM64. The earlier nine-test suite, including replay and native sandbox/cache
cases, also passed in Ubuntu 22.04 Linux x86-64 CI; see [Linux evidence](bazel-findings.md#ci-repair-2026-09-05).
Linux validation runs through the setup and Nix CI workflows.
Cross-platform artifact reuse remains unproven.

The first staging slice now compares identical consumer bundles across fresh
native macOS ARM64 executions; see [staging findings](staging-findings.md).
The first [native runtime slice](native-runtime-findings.md) now declares the Nix
reference closure and rejects incomplete declarations. The [.NET runner](dotnet-runner-findings.md)
removes Python from build actions while retaining the Python experiment harness.
The [runner refactor](action-runner-refactor.md) moves policy into declared MSBuild
imports and strengthens the .NET request/process contracts.
The [runtime integrity extension](native-runtime-integrity-findings.md) adds
payload hashes, copied-library rejection/invalidation and loader diagnostics.
Next, force actual loaded-library substitution or denial of an observed host
dependency; full runtime closure and general host-read discovery remain open.
Ordinary package DLL/runtime assets need separate coverage. General graph export
(step 8) remains deferred until these boundaries are established.

## Milestone sequence

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

## Scope

One framework, Release, local execution and local disk cache. Linux x86-64 was
the initial platform target; current measured platform evidence is stated above. Remote execution, cross-platform support, multi-targeting, Native AOT, publishing, Razor/WPF, and arbitrary NuGet build targets need separate evidence. Pinned bootstrap tools alone do not make build actions hermetic.

## Recorded results

Codex setup and CI are established. The initial process contract and six e2e scenarios were committed before implementation. See [e2e scope](e2e-scope.md), [interfaces](interfaces.md), and [findings](findings.md).

Step 4 now has a runnable path probe and a seventh e2e test. On macOS ARM64 with
the pinned Nix SDK, moving the bundle preserves App-only compilation, but moving
the project workspace causes raw MSBuild `MSB4252` at `GetTargetFrameworks`. A
fresh dependency cache at the new path succeeds. See [path findings](path-findings.md)
for commands, controls, and limitations. Raw-cache relocation remains unsupported.

Step 5 now has a public-API replay plugin, an independent probe, and black-box
acceptance coverage. Relocated Build, App-only edit, and narrow Publish succeeded
on macOS ARM64 after deleting the producer, with strict isolation and no Shared
compilation. See [replay findings](replay-findings.md).

Steps 6 and 7 now have an explicit two-target Bazel rule, Shared-only producer,
App dependency replay, and a native sandbox/cache harness. Cold, unchanged,
App edit, Shared edit, cleared-output disk-cache reuse, and a fresh Bazel output
base are measured on macOS ARM64. See [Bazel findings](bazel-findings.md) and the
[process contract](bazel-interface.md). Subsequent input-identity experiments
are recorded below.

The first action-identity hardening experiment now covers imported targets,
generated-source data, declared versus ambient environment, App restore metadata
and host-identity changes. Python runtime files are declared; direct isolated
Python execution replaces the shell launcher, and remote execution/cache use is
disabled. See [identity findings](action-identity-findings.md). The following
package experiment extends that input boundary.

The pinned package-input experiment now stages verified archive payloads using
per-project restore manifests. Package data and target upgrades rebuild Shared
and App; missing, corrupt and stale-version inputs fail before compilation.
See [package findings](package-input-findings.md). This is build-only package
coverage, with no binary/runtime assets or arbitrary package closure claim.
See the current status above for remaining work.

The [staging experiment](staging-findings.md) separates diagnostic outputs from
consumer bundles, maps compiler paths and narrows Shared's intermediate handoff
to the reference assembly. A fresh output base with an empty cache forces real
executions and compares all bundle bytes and executable bits. Runtime closure
and broader output discovery remain open.
