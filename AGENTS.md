# Repository guidance

Use a separate Git worktree for each change.

## Goal and current state

The sole build interface is `msbuild/defs.bzl` / `msbuild/graph.bzl` with
`tools/GraphBuild` and its MSBuild project-cache plugin. ProjectSync emits explicit
graph contracts; ArtifactTools handles artifact extraction/composition and launch.
See docs/api.md and docs/support.md for scope and limits.
Bazel 8.8.0 and 9.2.0 are supported; 9.2.0 remains the default.

SDK toolchains consume verified archives or declared Bazel-produced artifacts;
do not add host-path SDK repositories. Historical commands need their recorded
revisions (linked in docs/support.md).
GitHub CI runs only when explicitly requested. Read README.md and docs/support.md
before implementing changes.

## Commands

- Install or refresh pinned tools: `bash scripts/setup.sh` (network required for missing downloads).
- Validate the current scaffold and tracked Starlark: `bash scripts/check.sh`.
- Validate owned .NET code style, warnings and fixture-policy isolation: `bash scripts/check-dotnet.sh`.
- Run graph acceptance: `python3 tests/graph_build/acceptance.py /tmp/new-acceptance-directory` after building the graph runner.
- Run .NET: `bash scripts/dotnet.sh <args>`.
- Run Bazel: `bash scripts/bazel.sh <args>`.
- Review changes: `git diff --check` and `git diff`.

Use wrappers and explicit tool overrides rather than relying on PATH changes.
Keep SDK/Bazelisk pins and bootstrap defaults consistent. Bazel versions come
from .bazelversion or USE_BAZEL_VERSION; do not add repository-managed Bazel
checksums. Linux persistent-worker
checks require the qualified Ubuntu ARM64 container; do not imply Linux x86-64
qualification from an ARM64 run. Use fresh disposable fixture directories. CI is
manual and must not be started without an explicit request.

## Implementation direction

- Retain normal SDK-style csproj files and MSBuild compilation. Do not replace MSBuild with rules_dotnet without discussing the change in direction.
- Prefer explicit project inputs, dependency edges and configuration in Bazel BUILD files.
- Keep the graph path independent of historical per-project and discovery/replay implementations.
- Identify graph nodes by project path plus global properties. MSBuild result caches hold metadata, not artifact contents.
- Distinguish project-graph isolation from filesystem hermeticity. Do not claim remote-cache correctness based only on a warm local build.
- Account for input discovery, restore assets, generated files, stable paths, and output staging explicitly. Record limitations rather than silently disabling isolation or sandboxing.
- Pin tools and dependencies. Keep generated build artifacts, downloaded SDKs, and machine-specific paths out of git.

## Evidence and scope

Keep experiments small and independently runnable. For behavioral changes, run the relevant experiment and document the command, observed result, and remaining limitations in docs/support.md or docs/performance.md. Clearly distinguish proposed behavior from measured results. Do not report a check as passing if tooling or network access prevented it.
