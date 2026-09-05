# Repository guidance

## Goal and current state

Explore whether Bazel can schedule/cache individual .NET project builds while MSBuild retains SDK and NuGet behavior. This repository currently contains environment setup only. Read README.md and docs/spike-plan.md before implementing the spike.

## Commands

- Install or refresh pinned tools: `bash scripts/setup.sh` (network required for missing downloads).
- Validate the current scaffold: `bash scripts/check.sh`.
- Run .NET: `bash scripts/dotnet.sh <args>`.
- Run Bazel: `bash scripts/bazel.sh <args>`.
- Review changes: `git diff --check` and `git diff`.

Use wrappers instead of assuming setup changed PATH in future shells. Linux x86-64 is the initial supported environment. Version pins are in global.json, .bazelversion, and scripts/toolchains.json; update them together. No application build or test command exists yet; add documented commands with the first sample projects.

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
