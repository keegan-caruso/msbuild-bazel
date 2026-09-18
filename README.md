# MSBuild rules for [Bazel](https://bazel.build)

`rules_msbuild` provides Bazel project-level scheduling and caching while retaining
MSBuild, NuGet, and .NET SDK build behavior.

**Support target:** deterministic CI builds within qualified project and operation
slices. Build-time dates/version inputs and file timestamp behavior must satisfy
the [deterministic CI contract](docs/deterministic-ci-contract.md). CI execution
alone does not establish determinism or compatibility.

**Status:** The explicit two-project Bazel adapter builds Shared and App in separate
native sandbox actions and reuses their outputs through a local disk
cache. Public-API dependency-result replay works across workspace paths.
[Action-identity checks](docs/action-identity-findings.md) and
[pinned build-package inputs](docs/package-input-findings.md) are implemented.

**Active scope:** The Starlark baseline now has local Linux ARM64 evidence through Apple container; further Linux x86-64 CI remains deferred. The [R04 Serilog library slice](docs/r04-integration-findings.md) now passes native macOS build, mutation and producer-free relocated cache acceptance; the unchanged upstream approval-test project also passes native build/test, mutation and relocated-cache acceptance ([test findings](docs/serilog-test-acceptance-findings.md)).

**Local MVP:** [v0.1.0-mvp.1 installation and adoption guide](docs/local-mvp-release.md)
covers the pinned native macOS ARM64/Nix Build/Test slice. See the
[release qualification and measured costs](docs/local-mvp-signoff.md) and
[frozen support contract](docs/local-mvp-contract.md). Preparation reuse reduces
preparation work; complete Build/Test still carries overhead on this small graph.

**Platform evidence:** The original nine-test suite, including replay and native
Bazel sandbox/cache cases, passed on macOS ARM64 and in Ubuntu 22.04 Linux x86-64
CI; see [Linux evidence](docs/bazel-findings.md#ci-repair-2026-09-05). The newer
identity and package tests have macOS results; Linux validation of those tests
is handled separately. Cross-platform artifact reuse remains unproven.

The [deterministic staging experiment](docs/staging-findings.md) now compares
consumer bundles across fresh sandbox executions on macOS ARM64.

**Runtime progress:** The [Nix runtime experiment](docs/native-runtime-findings.md)
declares native libraries and signing tools. The [.NET action runner](docs/dotnet-runner-findings.md)
uses the existing SDK. [Production preparation, Build/Test, cache transport and
setup now run without Python](docs/python-removal.md). Use
`bash scripts/build.sh` for the [native workflow](docs/native-workflow.md);
Python implementations remain as test oracles and experiment harnesses.
The [runtime integrity extension](docs/native-runtime-integrity-findings.md)
verifies declared payload hashes, tests copied-library changes and records loader
diagnostics. The [loaded JIT experiment](docs/loader-runtime-findings.md) stages a
private runtime and checks actual loading, invalid-image rejection and cache
invalidation. [Managed binary package acceptance](docs/binary-package-findings.md)
now passes on Linux, including transitive runtime assets, relocation and cache
recovery. **Graph export:** The configured graph exporter has passing Linux acceptance
[evidence](docs/graph-export-findings.md). The first [generated graph execution
slice](docs/graph-execution-findings.md) passes native macOS acceptance for a
Release/net10.0 package-free diamond. [Cache acceptance contracts](docs/graph-cache-contract.md)
and [real-project discovery](docs/real-project-pilot.md) are prepared in parallel;
the later acceptance results below supersede their initial unimplemented status.
The [first parallel batch](docs/parallel-tracks-findings.md) implements package-free
cache and handoff controls plus an existing-rule multi-language harness; combined
native validation is recorded there. The [R02 managed-package slice](docs/graph-package-plan.md) has native macOS
cache/relocation and PrivateAssets parity evidence, with Linux qualification pending.
General NuGet compatibility, RID-specific/native package assets, full runtime
closure, remote-cache correctness and cross-platform portability remain unproven.

The [forward roadmap](docs/roadmap.md) covers R01–R17 from this checkpoint through
a supported adapter. **Completed:** the selected R02–R04 package/configuration/test-rule
[qualification gates](docs/r02-r04-validation-findings.md) pass on native macOS,
including the unchanged upstream approval test, a real PolySharp version mutation
and reference consumption after cache recovery. **R05:** [selected generator and reference-role qualification](docs/r05-qualification.md)
adds classic/incremental project generators, package combinations, diagnostic-only
analyzers and recovered consumer compilation. Spectre.Console, CommunityToolkit
and Dapper.AOT add native macOS mutation, behavioral and relocated-cache evidence,
with explicit remaining combinations. **Preparation reuse:** implemented and measured
for the local MVP; broader work remains in the
[active execution order](docs/roadmap.md#active-execution-order).
[RUL-5 discovery identity and eligibility](docs/discovery-contract.md) now cover
the selected native macOS SDK/Serilog slice. [RUL-6 preparation reuse](docs/preparation-reuse-findings.md) adds opt-in leased reuse, integrity verification and atomic publication. [Repeated measurements](docs/serilog-performance-findings.md) are
complete and show adapter overhead for this small graph; useful performance at
scale, broader R03 entry points and Linux qualification remain separate.
Later tracks cover specialized SDKs, platform workloads and independent remote
workers; see the [coverage matrix](docs/scenario-coverage.md) and
[parallel dependency graph](docs/roadmap-graph.md).

The opt-in [native MSBuild project cache](docs/native-cache-serilog.md) now admits
the pinned Serilog library and approval-test graph through verified evaluated
inputs and package manifests. Native Bazel builds preserve SDK runtime outputs;
explicit HTTP snapshots support fresh-workspace project recovery. The
[API/runtime boundary](docs/native-api-runtime.md) reuses ordinary project
compilation across unchanged-reference body edits and composes current runtime
outputs separately. This selected same-host macOS slice does
not qualify code coverage, arbitrary packages or cross-host remote caching.
The [native Build/Test command](docs/native-workflow.md) adds normal Bazel test
execution and opt-in leased preparation reuse. [Complete workflow measurements](docs/native-workflow-performance.md)
separate default CLI costs from optional retained-controller behavior. The
[overhead follow-up](docs/native-workflow-optimization.md) measures retained inputs,
package reuse, identity sharing and larger graphs.

[Remote preparation snapshots](docs/remote-preparation.md) let fresh consumers
reuse qualified discovery and native plans through the normal workflow command,
with explicit snapshot digests and current-input verification.
[NuGet global-cache reuse](docs/nuget-cache-reuse.md) avoids retransferring verified
package payloads and keeps mutable global caches outside build actions.
[Split preparation objects](docs/preparation-components.md) also reuse unchanged
source groups, graph metadata, and SDK evidence, with shaped-network measurements.

The opt-in [Bazel-owned preparation lane](docs/bazel-owned-preparation.md) moves
discovery behind Bazel's remote-cache lookup while retaining MSBuild, NuGet and
the existing strict discovery sandbox. It wraps the pinned Nix SDK and declares
its native runtime closure. [Direct inputs and project actions](docs/bazel-direct-inputs.md)
separate structural discovery from source binding and move tools and NuGet archives
into Bazel repositories. Individual project actions are an additional opt-in mode;
they remove snapshot/priming protocols. Development targets large-graph cache hits
and edits, accepting additional overhead on small graphs.
The established workflow remains the default.

## Quick start

Linux x86-64 or ARM64 (glibc), with Bash, curl, tar, gzip, sha256sum, and standard .NET runtime dependencies
(Python 3 is needed only to run repository tests and experiment harnesses):

```sh
bash scripts/setup.sh
bash scripts/check.sh
bash scripts/dotnet.sh --info
bash scripts/bazel.sh version --gnu_format
```

Setup installs checksum-pinned .NET SDK 10.0.400 and Bazel 8.4.2 into ignored `.tools/` directories without sudo. These are fixed experimental baselines, not a claim to be the latest releases. Bazel's distribution includes its JDK. The wrapper defaults to a persistent Bazel server; set `RULES_MSBUILD_BAZEL_MODE=batch` for one-shot execution. Container probes shut down their servers before cleanup. Setup is repeatable and needs internet access only for missing downloads. Use the wrappers in each new shell; setup exports do not persist into Codex's agent session.

The [SDK upgrade findings](docs/sdk-upgrade-findings.md) record validation and compatibility limits for SDK 10.0.400.

## Apple container smoke test

For a disposable Linux smoke test on an Apple silicon Mac with Apple `container`
installed and running, use `bash scripts/test-apple-container.sh`. It builds and
runs a copy of Shared -> App and checks the output. See the
[Apple container runbook](docs/apple-container-runbook.md) for prerequisites,
logs, and the separate Bazel sandbox/cache experiment.
Run `bash scripts/test-apple-container-scenarios.sh` for the broader graph,
graph-execution and end-to-end suites, or pass suite names to select a subset.

## Nix development shell

The flake provides native toolchains for macOS ARM64 (`aarch64-darwin`) and Linux x86-64 (`x86_64-linux`). Install [Nix](https://nixos.org/download/), then enter the shell:

```sh
nix --extra-experimental-features 'nix-command flakes' develop
bash scripts/tooling.sh setup-starlark
bash scripts/check.sh
bash scripts/bazel.sh query //:repo_setup --noshow_progress
python3 -m unittest discover -s tests/e2e -v
```

If flakes are already enabled in your Nix configuration, use `nix develop`, or run a single command with `nix develop -c python3 -m unittest discover -s tests/e2e -v`. No `scripts/setup.sh` step is needed inside this shell. Acquire the separately checksum-pinned Buildifier once with `bash scripts/tooling.sh setup-starlark`; it is validation tooling and is not used by compilation or graph preparation. When trying an uncommitted flake before its files are tracked by Git, use `develop path:.` instead of `develop`.

`flake.lock` separately locks the .NET SDK 10.0.400 Nixpkgs input and the existing Bazel 8.4.2 input. The shell checks those versions against `scripts/toolchains.json`. It uses the upstream binary .NET SDK packaged by Nixpkgs and Nixpkgs' source-built, patched Bazel; that Bazel reports the suffix `- (@non-git)`, which the check script accepts. It is not byte-identical to the Bazel release binary used by setup.

The shell supplies `RULES_MSBUILD_DOTNET_ROOT` (the directory containing `dotnet`) and `RULES_MSBUILD_BAZEL` (the executable path). The wrappers, driver, probes, and tests use these explicit overrides; outside Nix they retain the repository-local `.tools/` defaults. Restore and build outputs remain writable and local to the repository or copied test workspace, outside the Nix store.

Initial Nix downloads and each test workspace's NuGet restore require network access. This is a development environment, not a sandboxed Nix derivation of the application or proof of hermetic builds. macOS runs are native, not Linux emulation. The separate Nix workflow runs the version checks, Bazel query, and e2e tests on Ubuntu only; see [findings](docs/findings.md) for measured validation.

### Bazel version experiments on macOS ARM64

Select an exact checksum-pinned official Bazel release with
`nix develop .#bazel-7_7_1`, `.#bazel-8_4_2`, `.#bazel-8_8_0`, or
`.#bazel-9_2_0`. These experimental shells retain the same pinned .NET SDK.
The default shell continues to use Nixpkgs' patched Bazel 8.4.2; the named
8.4.2 shell deliberately uses the official release binary for comparison with
the other releases. Version selection does not change `.bazelversion`.
The wrappers check the shell-selected version and use Bazel's native output-root
default. Explicit startup options remain available to callers. The matrix runs
each version in a separate copy of one source snapshot, including identical initial
module lockfiles. Linux currently exposes only the existing default shell.

Run all four entries, retaining each failure and continuing to later gates:

```sh
python3 scripts/test-nix-bazel-matrix.py --output /tmp/rules-msbuild-bazel-matrix
```

The output directory must be new and outside the checkout, so temporary fixtures
do not inherit repository build configuration. See [layout and version qualification](docs/nix-bazel-layout-findings.md)
for current commands and results, and [initial matrix findings](docs/nix-bazel-matrix-findings.md)
for the original failures and distribution differences.

## Codex cloud environment

Select this repository in the Codex environment settings and configure:

- Setup script: `bash scripts/setup.sh`
- Maintenance script: `bash scripts/setup.sh`
- No secrets required for this scaffold.

The script lives in the repository; committing it does not configure the hosted environment automatically. Setup downloads from `builds.dotnet.microsoft.com` and `releases.bazel.build`. Future NuGet dependencies must be restored during setup before agent-phase offline builds can work.

Codex reads [AGENTS.md](AGENTS.md) for project context and commands. See the [implementation plan](docs/implementation-plan.md) for the next implementation steps.

The [terminology cleanup](docs/terminology-cleanup.md) records the current driver,
environment and fixture names. Commands below use the current interfaces.

## .NET code style

C# style and warning policies apply to the repository's tools and unit tests.
Builds enforce the selected EditorConfig rules and treat compiler/analyzer warnings
as errors. Run the complete owned-project check with:

```sh
bash scripts/check-dotnet.sh
```

This rebuilds the tools and unit tests with MSBuild warnings also treated as errors,
checks formatter output (including System-first imports), and verifies that deliberate
violations fail. Experimental fixtures retain their own build policy. See [code-style validation](docs/code-style-findings.md) for scope and evidence.

## Adapter contracts and tests

The [interface contract](docs/interfaces.md) and [e2e scope](docs/e2e-scope.md) were committed before the driver implementation. Run the black-box tests with:

```sh
python3 -m unittest discover -s tests/e2e -v
```

Tests copy the two-project fixture to fresh temporary directories. Restore downloads the pinned Traversal SDK from NuGet into each workspace's own package directory; tests currently require network access. Compilation is then invoked separately without restore.

The first milestone exports a Shared project's MSBuild result cache and bin/obj artifacts, removes local build outputs, and consumes that bundle in an isolated App build. It also tests an App-only edit and rejects missing artifacts, mismatched configuration, and workspace relocation. Failed workspaces are retained for diagnosis.

That first milestone retains its same-path restriction as a control: raw MSBuild
result caches fail when the project workspace moves. The later public-API replay
experiment supports relocated workspaces, and the Bazel adapter uses that replay
boundary. See the [first-milestone findings](docs/findings.md) and
[e2e scope](docs/e2e-scope.md) for the separate contracts.

Run the path probe independently to retain copied workspaces, logs, the raw MSBuild command, and a JSON report (the output directory must not exist):

```sh
python3 tools/probe_paths.py --output artifacts/path-probe
```

Use this command inside `nix develop` on macOS ARM64. The probe records the raw relocation build's exit status; an observed relocation failure does not itself fail the probe command. The e2e test asserts the measured `MSB4252` failure and both successful controls. See [path findings](docs/path-findings.md) for the implications for Bazel.

Run the separate public-API replay probe with retained evidence:

```sh
python3 tools/probe_replay.py --output artifacts/replay-probe
```

See [replay findings](docs/replay-findings.md) for target contracts, validation
cases, and remaining limitations.

Run the Bazel action and cache probe (requires native OS sandbox support):

```sh
python3 tools/probe_bazel.py --output artifacts/bazel-probe
```

This generates a copied Bazel workspace containing `//:shared` and `//:app`.
See [Bazel findings](docs/bazel-findings.md) for the measured action matrix and
host-runtime limitations. Add `--identity-probe` to test imported targets,
generated-source data, environment and host-identity invalidation. Use
`--package-probe` instead to test pinned NuGet package payloads, build-target
upgrades and rejection of missing/corrupt/stale package inputs.
Use `--binary-package-probe` for managed reference/runtime DLLs, a transitive
package dependency, direct/transitive upgrades and relocated output staging.
See the [binary package contract](docs/binary-package-plan.md) and
[validation record](docs/binary-package-findings.md) for scope and evidence.
Use `--staging-probe` to compare complete consumer bundles from two fresh builds
with separate output bases and empty disk caches.
Inside `nix develop`, use `--native-runtime-probe` to declare the transitive Nix
runtime closure and check rejection of incomplete action inputs.

## Validation

See the [adapter validation strategy](docs/validation.md) for the Bazel test
layers, acceptance matrix, runnable suites and evidence requirements. It separates
recorded probe results and the [implemented Starlark baseline](docs/starlark-core-findings.md)
from the remaining package/configuration/test-rule and Bazel-version gates.

`bash scripts/check.sh` checks shell syntax, version-pin consistency, installed tool versions, and tracked Starlark formatting/lint. It does not run the integration experiments. GitHub CI is manual-only. The Linux workflow defaults to quick checks; select full only for broad native acceptance. Nix and macOS qualification remain separate explicit requests. See the [CI scope and cost guide](docs/ci-scope.md).

## References

- [Codex repository instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Codex cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environment)
- [MSBuild static graph](https://github.com/dotnet/msbuild/blob/main/documentation/specs/static-graph.md)
- [MSBuild Traversal](https://github.com/microsoft/MSBuildSdks/tree/main/src/Traversal)
