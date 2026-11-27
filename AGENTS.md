# Repository guidance

Use a separate Git worktree per change.

`WORK_QUEUE.md` is the authoritative work queue: read it before starting, and update status, ownership, dependencies, worktree, and validation evidence via the lead instance. Parallelize independent slices across hosts/instances; design details only as needed. Max model: Sol 6.1 (Terra 6.1 for simpler tasks). Create one named Rex session per work item on its execution host, record host/session ID in the queue, and reuse panes instead of opening a tab per command. After review and integration, preserve evidence, remove clean completed worktrees, close that item's Rex session, and simplify/remove completed queue entries. Never discard unmerged/unrelated work, sessions, or independently managed services; pausing work does not authorize discarding it.

## Goal and current state

Sole build interface: `msbuild/defs.bzl` / `msbuild/graph.bzl` with `tools/GraphBuild` and its MSBuild project-cache plugin. `ProjectSync` emits explicit graph contracts; `ArtifactTools` handles artifact extraction/composition and MTP/VSTest protocols. Baseline: Bazel 9.3.3. See `docs/api.md` and `docs/support.md` for scope/limits.

SDK toolchains consume verified archives or declared Bazel-produced artifacts; never add host-path SDK repositories. Historical commands require their recorded revisions (linked in `docs/support.md`). GitHub CI runs only when explicitly requested. Read `README.md` and `docs/support.md` before implementing changes.

## Commands

- Install/refresh pinned tools (network required for missing downloads): `bash scripts/setup.sh`
- Validate scaffold and tracked Starlark: `bash scripts/check.sh`
- Validate owned .NET style, warnings, and fixture-policy isolation: `bash scripts/check-dotnet.sh`
- Run graph acceptance (after building graph runner): `python3 tests/graph_build/acceptance.py /tmp/new-acceptance-directory`
- Run .NET / Bazel: `bash scripts/dotnet.sh <args>` / `bash scripts/bazel.sh <args>`
- Review changes: `git diff --check` and `git diff`

Use wrappers and explicit tool overrides instead of PATH changes. Keep SDK/Bazelisk pins and bootstrap defaults consistent. Bazel versions come from `.bazelversion` or `USE_BAZEL_VERSION`; do not add repo-managed Bazel checksums. Linux persistent-worker checks require the qualified Ubuntu ARM64 container (do not imply Linux x86-64 qualification from ARM64). Use fresh disposable fixture directories. Never start CI without explicit request.

## Implementation direction

- Keep standard SDK-style `.csproj` files and MSBuild compilation; do not replace MSBuild with `rules_dotnet` without discussion.
- Prefer explicit project inputs, dependency edges, and configuration in `BUILD` files.
- Keep the graph/plugin model as the only backend (no native-batch or per-project backends); keep it independent of historical per-project and discovery/replay implementations.
- Identify graph nodes by project path + global properties. MSBuild result caches hold metadata, not artifact bytes.
- Distinguish project-graph isolation from filesystem hermeticity; never claim remote-cache correctness from a warm local build.
- Account explicitly for input discovery, restore assets, generated files, stable paths, and output staging; document limitations rather than disabling isolation/sandboxing.
- Pin tools/dependencies; keep generated artifacts, downloaded SDKs, and machine-specific paths out of Git.

## Evidence and scope

Keep experiments small and independently runnable. Record command, observed result, and limits for behavioral changes in `docs/support.md` or `docs/performance.md`. Distinguish proposals from measured behavior; report blocked or unrun checks honestly.

## Documentation

- Write for current users in plain language with short, dense sections; replace stale content instead of appending logs.
- Scope by file and cross-link rather than repeating: `README.md` (value, entry points, scoped perf summary), `docs/design.md` (design), `docs/api.md` (configuration), `docs/support.md` (qualification/limits), `docs/performance.md` (measurements/reproduction).
- Keep the quick start practical with separate downloaded-SDK and source-built-SDK scenarios, explicit prerequisites and producer/toolchain boundaries, labeled non-standalone handoffs, and API-verified examples.
- Summarize evidence with scope, pins, method, results, and material limits. Separate paired timings from profiles and correctness controls. Link pinned revisions for history; keep raw reports out of Git.
- Use tables for comparisons and code blocks for commands. Cut redundant caveats, chronology, and speculation; keep decision-relevant limits.
- For docs-only changes, check local links/anchors, snippet syntax, and `git diff --check`; run builds only to validate changed instructions; never start CI.
