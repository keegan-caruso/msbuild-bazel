# msbuild-bazel

A spike exploring Bazel project-level scheduling and caching while retaining MSBuild, NuGet, and the .NET SDK build behavior.

**Status:** The explicit two-project Bazel adapter builds Shared and App in separate
native sandbox actions and reuses their outputs through a local disk
cache. Public-API dependency-result replay works across workspace paths.
[Action-identity checks](docs/action-identity-findings.md) and
[pinned build-package inputs](docs/package-input-findings.md) are implemented.

**Platform evidence:** The original nine-test suite, including replay and native
Bazel sandbox/cache cases, passed on macOS ARM64 and in Ubuntu 22.04 Linux x86-64
CI; see [Linux evidence](docs/bazel-findings.md#ci-repair-2026-09-05). The newer
identity and package tests have macOS results; Linux validation of those tests
is handled separately. Cross-platform artifact reuse remains unproven.

The [deterministic staging experiment](docs/staging-findings.md) now compares
consumer bundles across fresh sandbox executions on macOS ARM64.

**Runtime progress:** The [Nix runtime experiment](docs/native-runtime-findings.md)
declares native libraries and signing tools. The [.NET action runner](docs/dotnet-runner-findings.md)
uses the existing SDK; Python remains only in preparation and tests.
The [runtime integrity extension](docs/native-runtime-integrity-findings.md)
verifies declared payload hashes, tests copied-library changes and records loader
diagnostics. The [loaded JIT experiment](docs/loader-runtime-findings.md) stages a
private runtime and checks actual loading, invalid-image rejection and cache
invalidation. [Managed binary package acceptance](docs/binary-package-findings.md)
now passes on Linux, including transitive runtime assets, relocation and cache
recovery. **Next:** General graph export for the deliberately local-only adapter.
General NuGet compatibility, RID-specific/native package assets, full runtime
closure, remote-cache correctness and cross-platform portability remain unproven.

## Quick start

Linux x86-64 (glibc), with Bash, Python 3, curl, tar, and standard .NET runtime dependencies:

```sh
bash scripts/setup.sh
bash scripts/check.sh
bash scripts/dotnet.sh --info
bash scripts/bazel.sh version --gnu_format
```

Setup installs checksum-pinned .NET SDK 10.0.100 and Bazel 8.4.2 into ignored `.tools/` directories without sudo. These are fixed experimental baselines, not a claim to be the latest releases. Bazel's distribution includes its JDK. The wrapper uses batch mode for short-lived agent containers. Setup is repeatable and needs internet access only for missing downloads. Use the wrappers in each new shell; setup exports do not persist into Codex's agent session.

## Nix development shell

The flake provides native toolchains for macOS ARM64 (`aarch64-darwin`) and Linux x86-64 (`x86_64-linux`). Install [Nix](https://nixos.org/download/), then enter the shell:

```sh
nix --extra-experimental-features 'nix-command flakes' develop
bash scripts/check.sh
bash scripts/bazel.sh query //:repo_setup --noshow_progress
python3 -m unittest discover -s tests/e2e -v
```

If flakes are already enabled in your Nix configuration, use `nix develop`, or run a single command with `nix develop -c python3 -m unittest discover -s tests/e2e -v`. No `scripts/setup.sh` step is needed inside this shell. When trying an uncommitted flake before its files are tracked by Git, use `develop path:.` instead of `develop`.

`flake.lock` locks Nixpkgs to a revision containing .NET SDK 10.0.100 and Bazel 8.4.2. The shell checks those versions against `scripts/toolchains.json`. It uses the upstream binary .NET SDK packaged by Nixpkgs and Nixpkgs' source-built, patched Bazel; that Bazel reports the suffix `- (@non-git)`, which the check script accepts. It is not byte-identical to the Bazel release binary used by setup.

The shell supplies `SPIKE_DOTNET_ROOT` (the directory containing `dotnet`) and `SPIKE_BAZEL` (the executable path). The wrappers, driver, probes, and tests use these explicit overrides; outside Nix they retain the repository-local `.tools/` defaults. Restore and build outputs remain writable and local to the repository or copied test workspace, outside the Nix store.

Initial Nix downloads and each test workspace's NuGet restore require network access. This is a development environment, not a sandboxed Nix derivation of the application or proof of hermetic builds. macOS runs are native, not Linux emulation. The separate Nix workflow runs the version checks, Bazel query, and e2e tests on Ubuntu only; see [findings](docs/findings.md) for measured validation.

## Codex cloud environment

Select this repository in the Codex environment settings and configure:

- Setup script: `bash scripts/setup.sh`
- Maintenance script: `bash scripts/setup.sh`
- No secrets required for this scaffold.

The script lives in the repository; committing it does not configure the hosted environment automatically. Setup downloads from `builds.dotnet.microsoft.com` and `releases.bazel.build`. Future NuGet dependencies must be restored during setup before agent-phase offline builds can work.

Codex reads [AGENTS.md](AGENTS.md) for project context and commands. See the [spike plan](docs/spike-plan.md) for the next implementation steps.

## Spike contracts and tests

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

`bash scripts/check.sh` checks shell syntax, version-pin consistency, and installed tool versions. It does not run the integration experiments. GitHub Actions separately runs fresh setup, repeated setup, Bazel package loading, and the e2e suite.

## References

- [Codex repository instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Codex cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environment)
- [MSBuild static graph](https://github.com/dotnet/msbuild/blob/main/documentation/specs/static-graph.md)
- [MSBuild Traversal](https://github.com/microsoft/MSBuildSdks/tree/main/src/Traversal)
