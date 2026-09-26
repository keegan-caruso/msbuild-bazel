# Dependency input audit

Bazel owns inter-project scheduling and caching; MSBuild retains project SDK and
NuGet behavior. This audit follows each input to its consumer before narrowing it.

## Compilation inputs and consumers

| Input | Consumer / reason | Decision |
| --- | --- | --- |
| Project, sources, imports, item files | Project evaluation, SDK targets, compiler and generators | Keep declared files and metadata |
| Compiler reference assemblies | ResolveAssemblyReferences and Csc; friend/implementation reference mode is explicit | Keep configured direct/transitive semantics |
| Runtime-only reference metadata for executable/test projects | ProjectRestore.Inject and SDK dependency manifest generation | Keep; not runtime implementation DLLs |
| Transitive restore-project JSON | ProjectRestore.Inject reconstructs NuGet graph identities, package requests and private edges | Keep even for direct-only compilation |
| NuGet package trees | Restore, package references, imported targets, analyzers and runtime export | Keep whole declared trees until asset-level separation preserves all consumers |
| Project analyzer implementations, helpers and packages | ProjectAnalyzers prepares executable analyzer load groups | Keep implementation closure, not just reference assemblies |
| Task implementations, helpers, packages and data | BuildTools and file bindings execute task code | Keep complete declared tool closure |
| Explicit project outputs, layouts and target-result items | SDK/custom targets consume these declared inputs | Keep the selected artifact role |
| Assembly selection identities | AssemblyContracts validates configured branch convergence | Keep small identity records |
| SDK and runner | MSBuild evaluation, restore, compilation and SDK tasks | Keep for compilation |
| Ordinary dependency runtime trees and runtime data | ApplicationLaunch and test execution | Already excluded from ordinary compilation; preserve in runfiles |

The implementation is in `msbuild/private/project.bzl`, `inputs.bzl`,
`selection.bzl` and `tools/ExplicitBuild`. Existing providers already separate
reference, runtime, tool and restore roles. No change to transitive reference
semantics is justified by this audit.

## Inputs to remove

- Assembly pairing reads reference/identity/restore files using the runner. It
  does not execute MSBuild and needs the runner runtime, not SDK compiler assets.
- Application/test launchers compose runtime files and execute the declared host.
  They need the runner runtime plus that host, not the complete build SDK. The
  legacy fallback host must retain all installed shared frameworks, including
  ASP.NET Core. Separately declared platform runtime closure files must remain.

## Validation plan

Assert action/runfiles membership in analysis tests. Exercise body/API edits,
runtime data, task/analyzer helper changes, fresh execution, worker reuse and
cache replay using small synthetic projects. Record results below before merging.
Full SDK retention for compilation and whole NuGet package trees are deliberate
limits, not claims that every file in those trees is necessary.
