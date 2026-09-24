# Development and toolchains

Run commands from the repository root. Use the wrappers in each new shell;
setup exports do not persist between shells.

## Linux setup

On Linux x86-64 or ARM64 (glibc), install Bash, curl, tar, gzip, sha256sum,
standard .NET runtime dependencies and Python 3. Python is used by example setup,
tests and experiment harnesses, not the production runner.

```sh
git clone https://github.com/keegan-caruso/msbuild-bazel.git
cd msbuild-bazel
bash scripts/setup.sh
bash scripts/check.sh
bash scripts/dotnet.sh --info
bash scripts/bazel.sh version --gnu_format
```

Setup installs checksum-pinned tools under ignored `.tools/` directories without
sudo and downloads only missing archives. Bazel defaults to a retained server;
set `RULES_MSBUILD_BAZEL_MODE=batch` for a fresh process per command.
Continue with the [runnable example](../examples/hello/README.md).
For macOS ARM64, use the Nix shell below.

## Nix development shell

The flake provides native toolchains for macOS ARM64 (`aarch64-darwin`) and Linux x86-64 (`x86_64-linux`). Install [Nix](https://nixos.org/download/), then enter the shell:

```sh
nix --extra-experimental-features 'nix-command flakes' develop
bash scripts/tooling.sh setup-starlark
bash scripts/check.sh
bash scripts/bazel.sh query //:repo_setup --noshow_progress
bash scripts/check-dotnet.sh
```

If flakes are already enabled in your Nix configuration, use `nix develop`, or run a single command with `nix develop -c bash scripts/check-dotnet.sh`. No `scripts/setup.sh` step is needed inside this shell. Acquire the separately checksum-pinned Buildifier once with `bash scripts/tooling.sh setup-starlark`; it is validation tooling and is not used by application compilation. When trying an uncommitted flake before its files are tracked by Git, use `develop path:.` instead of `develop`.

`flake.lock` locks the .NET SDK 10.0.400 package and Nix packaging utilities.
The default shell uses checksum-pinned Bazel 9.2.0 release binaries: the macOS
pin is in `nix/bazel-versions.json`, and Linux uses `scripts/toolchains.json`.
On Linux, Nix patches the launcher for its runtime libraries and supplies its
pinned JDK 25 rather than the embedded JDK. The shell verifies selected versions;
existing Nix input locks are unchanged.

The shell supplies `RULES_MSBUILD_DOTNET_ROOT` (the directory containing `dotnet`) and `RULES_MSBUILD_BAZEL` (the executable path). The wrappers, probes, and tests use these explicit overrides; outside Nix they retain the repository-local `.tools/` defaults. Restore and build outputs remain writable and local to the repository or copied test workspace, outside the Nix store.

Initial Nix downloads and each test workspace's NuGet restore require network access. This is a development environment, not a sandboxed Nix derivation of the application or proof of hermetic builds. macOS runs are native, not Linux emulation. The separate Nix workflow runs the version checks, Bazel query, and explicit acceptance on Ubuntu only; see [CI scope](ci-scope.md) for the executable checks. A workflow definition is not passing evidence.

### Supported Bazel versions

The same rules support **Bazel 8.8.0 and 9.2.0**. The default `.bazelversion`,
Linux bootstrap and default Nix shell remain on 9.2.0. Select either supported
baseline on macOS ARM64 or Linux x86-64 without changing tracked pins:

```sh
nix develop .#bazel-8_8_0
# Or: nix develop .#bazel-9_2_0
bash scripts/check.sh --toolchain-only
bash scripts/bazel.sh query //:repo_setup --lockfile_mode=off
```

Outside Nix, an existing installation can be selected explicitly (including
Linux ARM64). Export both values so repository checks validate the chosen release:

```sh
export RULES_MSBUILD_BAZEL=/absolute/path/to/bazel-8.8.0
export RULES_MSBUILD_BAZEL_VERSION=8.8.0
bash scripts/check.sh --toolchain-only
```

This override selects an installed binary; `setup.sh` still installs the default.
Use separate Bazel output bases when alternating versions to avoid server restarts.
The checked-in module lockfile belongs to the default version; use
`--lockfile_mode=off` for alternate-version checks to avoid rewriting it. Normal
builds may regenerate their version's lockfile; do not commit that incidental
change. Neither lockfile nor cache entries are promised to be interchangeable
between versions.

Bazel 8.8.0 replaces the previous 8.4.2 baseline. See the
[8.8.0 upgrade checks](bazel-8.8-upgrade.md) for its validation scope.
The existing [full Orchard timing evidence (historical)](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/bazel-9.2-orchard-performance.md)
compares 8.4.2 with 9.2.0; those measurements do not describe 8.8.0.
Support targets these exact releases, not every 8.x or 9.x release.

### Additional version experiments on macOS ARM64

The named `.#bazel-7_7_1` Nix shell remains available for
experiments; it is outside the two supported baselines. All named shells retain
the same pinned SDK and select an exact checksum-pinned Bazel release.

Run all three entries, retaining each failure and continuing to later gates:

```sh
python3 scripts/test-nix-bazel-matrix.py --output /tmp/rules-msbuild-bazel-matrix
```

The output directory must be new and outside the checkout, so temporary fixtures
do not inherit repository build configuration. See [layout and version qualification (historical)](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/nix-bazel-layout-findings.md)
for historical results, and [initial matrix findings (historical)](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/nix-bazel-matrix-findings.md)
for the original failures and distribution differences.

## Codex cloud environment

Select this repository in the Codex environment settings and configure:

- Setup script: `bash scripts/setup.sh`
- Maintenance script: `bash scripts/setup.sh`
- Public bootstrap downloads require no secrets.

The script lives in the repository; committing it does not configure the hosted environment automatically. Setup downloads from `builds.dotnet.microsoft.com` and `releases.bazel.build`. NuGet dependencies must also be restored during setup before agent-phase offline builds can work.

Codex reads [AGENTS.md](../AGENTS.md) for project context and commands. See the [implementation plan](implementation-plan.md) for the next implementation steps.

## .NET code style

C# style and warning policies apply to the repository's .NET tools.
Builds enforce the selected EditorConfig rules and treat compiler/analyzer warnings
as errors. Owned C# requires braces around control-flow bodies, expanded blocks,
consistent modifier ordering, explicit accessibility, readonly fields when possible,
file-scoped namespaces and usings outside namespaces. Unused private members and
unnecessary assignments are rejected. Import sorting is enforced by the formatter
check, not the compiler.

Run the active tooling and explicit-runner checks with:

```sh
bash scripts/check-dotnet.sh
```

This rebuilds `Tooling` and `ExplicitBuild` with MSBuild warnings also treated as errors,
checks all warning-level formatter diagnostics (including System-first imports), and verifies that deliberate
violations fail.
Experimental fixtures retain their own build policy. See [code-style validation (historical)](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/code-style-findings.md) for scope and evidence.

The stricter policy was checked on 2026-09-23 with SDK 10.0.400 on macOS ARM64:
both Release builds and formatter checks passed, as did 5 style tests (including
nine diagnostic rejection cases), 6 tooling tests and 26 explicit-runner tests.
The Linux bootstrap simulations used GNU coreutils for `sha256sum`. These checks
do not claim new platform or upstream-build qualification.

## Validation

See [explicit rule acceptance](explicit-bazel-rules.md) and
[worker qualification](explicit-linux-workers.md) for current executable
checks. The [historical overview (historical)](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/historical-overview.md) preserves the
older adapter contracts and experiment commands.

`bash scripts/check.sh` checks shell syntax, version-pin consistency, installed tool versions, and tracked Starlark formatting/lint. It does not run the integration experiments. GitHub CI is manual-only. The Linux workflow defaults to quick checks; select full to include explicit-rule acceptance. Nix has a separate manual workflow; macOS qualification is local. See the [CI scope and cost guide](ci-scope.md).
