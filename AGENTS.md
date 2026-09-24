# Repository guidance

Use a separate Git worktree for each change.

## Goal and current state

The active build interface is `msbuild/defs.bzl` plus `tools/ExplicitBuild`: explicit
per-project Bazel inputs and dependencies with SDK compilation retained in MSBuild.
The full 202-project Orchard CMS graph has Linux ARM64 compilation, edit, runtime
and cache-recovery evidence. See docs/explicit-bazel-rules.md,
docs/explicit-linux-workers.md and docs/orchard-stable-worker-paths.md for limits.
Bazel 8.8.0 and 9.2.0 are supported baselines; 9.2.0 remains the default.

The old discovery/replay implementations and dependent tests have been removed.
Toolchain checks use standalone tools/Tooling. Keep local_dotnet_sdk in
bazel/msbuild.bzl: explicit builds still use it. Historical commands require the
revisions recorded in docs/history.md. GitHub CI runs only
when explicitly requested. Read README.md and docs/implementation-plan.md before
implementing changes.

## Commands

- Install or refresh pinned tools: `bash scripts/setup.sh` (network required for missing downloads).
- Alternative native environment: `nix develop` (flakes enabled), for macOS ARM64 or Linux x86-64; no setup script needed inside the shell.
- Acquire pinned Starlark validation tooling inside Nix: `bash scripts/tooling.sh setup-starlark` (setup.sh does this outside Nix).
- Validate the current scaffold and tracked Starlark: `bash scripts/check.sh`.
- Validate owned .NET code style, warnings and fixture-policy isolation: `bash scripts/check-dotnet.sh`.
- Run explicit acceptance: `python3 tests/explicit_msbuild/acceptance.py /tmp/new-acceptance-directory` after building the runner.
- Run .NET: `bash scripts/dotnet.sh <args>`.
- Run Bazel: `bash scripts/bazel.sh <args>`.
- Review changes: `git diff --check` and `git diff`.

Use wrappers and explicit tool overrides rather than relying on PATH changes.
Keep SDK/Bazel pins and bootstrap/Nix defaults consistent. Linux persistent-worker
checks require the qualified Ubuntu ARM64 container; do not imply Linux x86-64
qualification from an ARM64 run. Use fresh disposable fixture directories. CI is
manual and must not be started without an explicit request.

## Implementation direction

- Retain normal SDK-style csproj files and MSBuild compilation. Do not replace MSBuild with rules_dotnet without discussing the change in direction.
- Prefer explicit project inputs, dependency edges and configuration in Bazel BUILD files.
- Keep the current explicit build path independent of historical graph exporters and replay controllers.
- Identify graph nodes by project path plus global properties. MSBuild result caches hold metadata, not artifact contents.
- Distinguish project-graph isolation from filesystem hermeticity. Do not claim remote-cache correctness based only on a warm local build.
- Account for input discovery, restore assets, generated files, stable paths, and output staging explicitly. Record limitations rather than silently disabling isolation or sandboxing.
- Pin tools and dependencies. Keep generated build artifacts, downloaded SDKs, and machine-specific paths out of git.

## Evidence and scope

Keep experiments small and independently runnable. For behavioral changes, run the relevant experiment and document the command, observed result, and remaining limitations in docs/implementation-plan.md or a linked findings file. Clearly distinguish proposed behavior from measured results. Do not report a check as passing if tooling or network access prevented it.
