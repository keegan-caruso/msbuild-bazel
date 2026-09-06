# Repository guidance

## Goal and current state

Explore whether Bazel can schedule/cache individual .NET project builds while MSBuild retains SDK and NuGet behavior. The same-path boundary, raw-cache path probe, and public-API dependency-result replay are implemented. Replay succeeds at a new workspace path on macOS ARM64 (docs/replay-findings.md). The explicit two-target Bazel adapter now has native macOS sandbox and local disk-cache evidence (docs/bazel-findings.md). Action-identity perturbations and Python runtime declarations are measured on macOS (docs/action-identity-findings.md). Pinned build-package payloads and package upgrade/rejection tests now pass on macOS (docs/package-input-findings.md). Next, address native runtime closure; deterministic consumer staging has fresh-execution evidence on macOS (docs/staging-findings.md), while binary package assets and general NuGet remain unproven. The user is handling Linux validation. Read README.md and docs/spike-plan.md before implementing the spike.

## Commands

- Install or refresh pinned tools: `bash scripts/setup.sh` (network required for missing downloads).
- Alternative native environment: `nix develop` (flakes enabled), for macOS ARM64 or Linux x86-64; no setup script needed inside the shell.
- Validate the current scaffold: `bash scripts/check.sh`.
- Run e2e acceptance tests: `python3 -m unittest discover -s tests/e2e -v` (network access for isolated restore).
- Run .NET: `bash scripts/dotnet.sh <args>`.
- Run Bazel: `bash scripts/bazel.sh <args>`.
- Review changes: `git diff --check` and `git diff`.

Use wrappers instead of assuming setup changed PATH in future shells. Linux x86-64 is the initial target environment. The earlier nine-test suite passed in Ubuntu 22.04 CI and on macOS ARM64; newer identity/package evidence is macOS-only, with Linux validation handled separately by the user. Version pins are in global.json, .bazelversion, and scripts/toolchains.json; update them together and keep flake.nix/flake.lock and the fixture pins consistent. Nix supplies explicit SPIKE_DOTNET_ROOT and SPIKE_BAZEL overrides; preserve the .tools defaults outside that shell. The fixture lives in tests/fixtures/two-projects. The e2e suite copies it; do not build directly into the source fixture. tools/spike.py implements the versioned process contract in docs/interfaces.md.

## Implementation direction

- Retain normal SDK-style csproj files and MSBuild compilation. Do not replace MSBuild with rules_dotnet without discussing the change in direction.
- Begin with Shared -> App, one target framework and Release configuration, and a traversal entry point.
- Prove isolated MSBuild builds and dependency artifact/result-cache handoff before building a general graph exporter.
- Identify graph nodes by project path plus global properties. MSBuild result caches hold metadata, not artifact contents.
- Distinguish project-graph isolation from filesystem hermeticity. Do not claim remote-cache correctness based only on a warm local build.
- Account for input discovery, restore assets, generated files, stable paths, and output staging explicitly. Record limitations rather than silently disabling isolation or sandboxing.
- Pin tools and dependencies. Keep generated build artifacts, downloaded SDKs, and machine-specific paths out of git.

## Evidence and scope

Keep experiments small and independently runnable. For behavioral changes, run the relevant experiment and document the command, observed result, and remaining limitations in docs/spike-plan.md or a linked findings file. Clearly distinguish proposed behavior from measured results. Do not report a check as passing if tooling or network access prevented it.
