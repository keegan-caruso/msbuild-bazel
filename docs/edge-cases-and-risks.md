# MSBuild / Bazel edge cases and risks

## Scope and evidence

The main risk is generalizing a passing fixture into a promise of arbitrary
MSBuild compatibility. The spike establishes a deliberately narrow contract:
Shared -> App, net10.0, Release, explicitly declared inputs, native sandbox
execution and local disk caching. Checksums establish integrity of declared
files, not completeness of the input set or filesystem hermeticity.

This register was added to main separately from [PR #2](https://github.com/keegan-caruso/msbuild-bazel/pull/2).
Package statements below include that PR's focused Linux acceptance evidence;
they do not imply its implementation is already merged into main. See the
[binary-package findings at the documented checkpoint](https://github.com/keegan-caruso/msbuild-bazel/blob/e2fd474cb25e018220d2ac452850d38547bfa938/docs/binary-package-findings.md)
and [passing focused job](https://github.com/keegan-caruso/msbuild-bazel/actions/runs/34011816923/job/101428853796).
Broader workflow status and additional platforms must be verified separately.

## Package edge cases

| Area | Evidence / boundary | Risk and next acceptance case |
| --- | --- | --- |
| Compile versus runtime assets | Distinct `ref/net10.0` and `lib/net10.0` DLLs are tested; App outputs match runtime DLL hashes, not reference hashes. | Add multiple compatible framework assets, RID-specific managed/native assets and satellite resources. Verify both selection and execution, not just file presence. |
| Transitive dependencies | Shared directly references Spike.Binary, which depends on Spike.Leaf. Both implementations execute. | Add diamond dependencies, conflicting versions and asset exclusions such as `PrivateAssets`, `IncludeAssets` and `ExcludeAssets`. Check that downstream restore and runtime outputs agree. |
| Restore coherence | Exact inline package versions, archive/payload hashes and selected stale-restore failures are checked. | Central package management, conditional references, lock files and the complete restore-input identity are not covered. Changing any relevant property, import, source configuration or lock state must invalidate preparation appropriately. |
| NuGet installation metadata | Binary resolution failed with `NETSDK1064` despite staged DLLs. Declaring an archive-derived `.nupkg.sha512` marker fixed the tested case. | Other package features may rely on further restored-directory metadata. Keep required metadata explicit, verified and relocatable; do not copy ambient cache state indiscriminately. |
| Package provenance | Repository-authored binary fixtures are built with the pinned SDK and their generated archives are hashed during preparation. | These are not independently pinned external binaries. External feeds need an explicit package identity, integrity and provenance policy; arbitrary feeds and signed-package behavior remain outside the demonstrated boundary. |

### Dependency handoff is not a standalone package bundle

App receives its own prepared restore state and complete declared package closure
as well as Shared's artifact/result bundle. The experiment does not prove that
Shared's bundle alone supplies every package asset a downstream consumer needs.
Keep the package closure and project-output contracts distinct when generalizing
the adapter.

## Adapter risks

| Area | Failure mode | Required control |
| --- | --- | --- |
| Undeclared inputs | A custom task reads a schema, environment variable, tool or host file absent from the action identity, permitting a stale cache hit. | Define a supported input contract, explicit custom-input declarations and negative missing-input tests. Project-graph isolation is not a filesystem sandbox. |
| Configured graph identity | One project path is treated as one node even when framework, configuration or other global properties differ. | Identify nodes by project path plus global properties. Initially reject configurations outside the tested contract; add configured-node acceptance before expanding support. |
| Dependency-result replay | Another SDK/project type requests targets or metadata not captured by the fixture's target set. | Derive and validate the supported target contract. Reject missing targets or mismatched properties rather than silently rebuilding dependencies or inventing results. |
| Path relocation | Cached metadata, generated files or task outputs retain producer workspace, package-root or SDK paths. | Preserve relocation tests with absent producer workspaces and fresh action/output roots. Raw MSBuild result caches failed project-workspace relocation; public-API replay only establishes the cases actually tested. |
| Output completeness | Fixture-specific staging omits resources, publish outputs or intermediates required by another consumer. | Establish explicit output contracts and test consumers after removing producer directories. Current staging of `bin` plus the Shared reference assembly is not general output discovery. |
| Output determinism | Timestamps, absolute paths, source-control metadata or task-specific generated content vary between fresh executions. | Compare complete consumer bundles, including executable bits, across genuinely fresh execution paths and empty caches. Keep diagnostics out of downstream inputs. |
| Runtime and host dependencies | Actions depend on undeclared OS files, dynamically loaded libraries or host tools. | Retain the host-bound/local-cache policy. One observed JIT substitution and a declared Nix closure do not prove complete host-read isolation or remote-cache correctness. |

Specialized SDK behavior—Razor, WPF, Native AOT, broader publishing, analyzers
and source generators—requires separate evidence. Successful compilation of the
current fixture does not establish compatibility with these workflows.

## Correctness versus cache efficiency

The current conservative boundary includes complete package payloads and broad
dependency bundles. It can therefore invalidate actions for unused package files
or implementation-only dependency changes that do not change a reference API.
That is primarily an efficiency issue, unlike omitted inputs, which can produce
incorrect results.

Do not narrow inputs merely to improve cache-hit rates. First establish which
files each supported action and downstream consumer actually require, then add
tests proving that excluded changes cannot affect observable results.

## Gates for the local-only graph exporter

1. **Publish and enforce a support boundary.** Explicitly reject unsupported
   configurations, package-reference forms and replay requests. Graph discovery
   alone does not establish build compatibility.
2. **Add a diamond-shaped fixture.** Exercise both project dependencies and a
   shared transitive package. Assert scheduling, version resolution, runtime
   output and absence of dependency recompilation inside consumer actions.
3. **Keep clean-state and relocation tests mandatory.** Remove preparation
   workspaces/feeds, test different action paths, verify cache recovery and
   require missing inputs to fail visibly.
4. **Define input/output contracts before exporter implementation.** Model
   configured nodes, dependency target results, package closures and consumer
   artifacts separately. Record unresolved custom-task behavior.
5. **Defer remote-cache/execution claims.** Full runtime/host closure and
   cross-machine reuse require their own acceptance evidence. They do not need
   to block an explicitly host-bound local-only exporter.

The exporter should automate the supported contract, not imply support for
arbitrary `.csproj` behavior.

## Related findings on main

- [Spike plan](spike-plan.md)
- [Raw-cache path probe](path-findings.md)
- [Public-API replay](replay-findings.md)
- [Action identity](action-identity-findings.md)
- [Package build inputs](package-input-findings.md)
- [Deterministic staging](staging-findings.md)
- [Loaded runtime-library boundary](loader-runtime-findings.md)
