# Development and toolchains

## Standard setup

Supported bootstrap hosts are macOS ARM64 and Linux x86-64/ARM64 with glibc.
Install Bash, curl, tar, gzip, Git, Python 3, and either `shasum` or `sha256sum`.
Linux also needs `/usr/bin/bwrap` (the `bubblewrap` package), enabled user
namespaces, and the .NET runtime libraries; Ubuntu 22.04 requires `libicu70`,
`libssl3`, `zlib1g` and CA certificates. Python is used for fixtures and tests,
not by the production build runner.

```sh
git clone https://github.com/keegan-caruso/msbuild-bazel.git
cd msbuild-bazel
bash scripts/setup.sh
bash scripts/dotnet.sh --info
bash scripts/bazel.sh --version
```

Setup installs checksum-pinned .NET SDK 10.0.400, Bazelisk 1.29.0, Buildifier
and Buildozer 8.2.1 under ignored `.tools/` directories without sudo. Repeat setup
reuses installed tools. Bazelisk selects and caches upstream Bazel; this repository
does not maintain Bazel download checksums or installation stamps.

Use wrappers from each new shell. For Python fixtures that read tool variables:

```sh
source scripts/env.sh
```

Continue with the [runnable example](../examples/hello/README.md).

## Bazel versions

`.bazelversion` selects **9.2.0**. The other supported baseline is **8.8.0**:

```sh
USE_BAZEL_VERSION=8.8.0 bash scripts/bazel.sh --version
```

`scripts/bazel-launcher.sh` preserves the caller's working directory and carries
this selection into generated workspaces, even when they contain another pin.
`scripts/bazel.sh` runs from the repository root and defaults to a retained server;
set `RULES_MSBUILD_BAZEL_MODE=batch` for a fresh process per command.

`RULES_MSBUILD_BAZEL` can select an explicit executable, and
`RULES_MSBUILD_DOTNET_ROOT` can select an SDK directory. For an explicitly supplied
Bazel binary, set `RULES_MSBUILD_BAZEL_VERSION` to its expected version.
`USE_BAZEL_VERSION` takes precedence over that legacy version setting.
`RULES_MSBUILD_BAZELISK` overrides the launcher binary. `BAZELISK_HOME` selects its
cache, defaulting to `.cache/bazelisk`. Benchmark reports record the actual Bazel
version and identify the launcher hash separately from a Bazel binary hash.

## Optional Nix environment

The pinned flake supports macOS ARM64 and Ubuntu x86-64:

```sh
nix develop
bash scripts/tooling.sh setup-starlark
bash scripts/check.sh
```

Enable `nix-command flakes` in Nix configuration, or pass
`--extra-experimental-features 'nix-command flakes'` to Nix. No `setup.sh` step is
needed inside the shell. Nix supplies .NET, Bazelisk and development utilities;
the shared tooling setup installs Buildifier and Buildozer. Bazelisk uses the same
version selection as standard setup, with no custom Bazel patches or JDK override.
The existing Nix SDK runtime-closure handling remains. NixOS is not qualified.

The lockfile pins the SDK and packaging utilities; tool versions match standard
setup. Initial acquisition requires network access. A Nix shell is a development
environment, not proof of application build hermeticity.

## BUILD-file tooling

Buildifier enforces formatting and lint in `check.sh`. Buildozer is available for
explicit edits and rule migrations, for example:

```sh
.tools/bin/buildozer 'add deps //Library:Library' //App:App
```

Buildozer is not invoked during ordinary compilation and does not infer MSBuild
project dependencies. Review its changes before committing.

## Containers and hosted environments

The toolchain image prewarms both supported Bazel versions in `BAZELISK_HOME`.
Acquisition happens before builds or benchmark timing. See
[Apple containers](apple-container-runbook.md) for setup.

Hosted environments can use `bash scripts/setup.sh` for setup and maintenance.
Downloads use Microsoft, GitHub and Bazel release hosts; no secrets are required.
Restore required NuGet packages before offline builds. Committing setup scripts
does not configure a hosting service automatically.

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

## Validation

`bash scripts/check.sh` checks shell syntax, pin consistency, selected tool versions,
and Starlark formatting/lint. `bash scripts/check-dotnet.sh` checks owned .NET code.

Run the same compatibility matrix with either setup:

```sh
python3 scripts/test-bazel-matrix.py --output /tmp/msbuild-bazel-matrix
```

It checks Bazel 8.8.0 and 9.2.0, SDK repositories and explicit-rule acceptance.
The output directory must be fresh and outside the checkout. On qualified Linux
workers, set `RULES_MSBUILD_EXPLICIT_WORKER=1` to exercise persistent compilation.
See [worker qualification](explicit-linux-workers.md) for additional controls.

GitHub CI is manual-only. The primary Linux workflow offers quick/full checks;
the optional Nix workflow checks the development environment. macOS validation
is local. See [CI scope](ci-scope.md).

### Bazelisk migration qualification

The migration passed fresh/repeated setup and the shared 8.8.0/9.2.0 matrix on
native macOS ARM64 and Ubuntu ARM64. Linux ARM64 also passed persistent-worker
acceptance and analyzer invalidation controls on both versions. The optional
macOS Nix shell passed the 9.2.0 matrix. The rebuilt ARM64 toolchain image started
both Bazel JVMs with networking disabled; Buildozer passed an actual edit check.

Ubuntu x86-64 under Apple emulation passed bootstrap, tool/style/unit checks and
SDK repository checks; the optional Nix shell passed checks with both Bazel
versions and a 9.2.0 query using the upstream embedded JVM. Full application
acceptance remains unqualified there: the compilation sandbox could not open
`/lib64/ld-linux-x86-64.so.2` under Rosetta. Native x86-64 application sandbox
qualification remains separate work. No GitHub CI was dispatched.

## Rule tests

Run `bash scripts/check-analysis.sh` for SDK-free rule checks on the selected
Bazel version. `rules_testing` covers provider propagation, compile versus runtime
inputs, output groups, runfiles, packages, tools, generation, restore and invalid
attribute combinations. A small `aquery` check covers execution requirements,
which Bazel does not expose through the Starlark Action API.

The fake SDK is registered only as a root-module development toolchain. Its
launcher always fails if executed; consumer modules do not inherit it. Fixtures
are manual targets, so the analysis suite does not build their outputs.

Quick checks and the shared version matrix run this suite. Real compilation,
MSBuild-discovered input validation, worker recovery, sandboxing, test protocol
execution and edit/cache invalidation remain integration checks. The settings
conflict/escape and tool binding/path rejection cases moved out of the VSTest
and tool integration scripts into analysis tests.

Qualification: all 25 analysis tests and execution-requirement checks passed on
macOS ARM64 and Linux ARM64 with Bazel 8.8.0 and 9.2.0. The full macOS version
matrix also passed owned-code checks, SDK repository tests and real-build
acceptance, including edit invalidation and cache recovery. No production rule
implementation changed in this migration.
