# Production readiness work queue

Authoritative work queue: update when assigning work, changing scope, finding blockers, completing checks, or integrating changes. Keep entries small until ready; remove completed entries once changes and evidence are preserved in docs/Git.

## Current status

All initial release qualification gates passed (latest `main` at `9377a27`; evidence in `docs/support.md`, `docs/performance.md`, and `.cache/qualified-artifacts/`). Each host retains only its primary checkout (Azure VM deallocated).

**Open / deferred:**
- Full Linux cross-host graph and source-runtime recovery remain open (native cross-host tiny-action reuse and same-host Linux whole-action recovery pass).
- Retained separate-scope pins (require separate decisions to migrate): `.github/workflows/linux.yml` (Ubuntu 22.04), historical SDK 10.0.100 archive (Ubuntu 22.04), and `tests/graph_build/native_aot.py` compiler/catalog (LLVM 14).

## Agreed release scope

- Bazel **9.3.2** only (8.x dropped; qualify later 9.x explicitly; keep historical measurement pins intact).
- Linux ARM64 in the qualified Ubuntu 26.04 environment, with workers supported and enabled by default (worker reliability is a release gate).
- Native macOS ARM64 with ordinary actions; native Linux x64 is not a launch blocker.
- Downloaded SDKs and source-built SDK/runtime workflows (define exact producer/consumer/Build/test/Pack/Publish/execution boundaries; do not infer full upstream parity or signing).
- Graph/plugin backend, declared toolchains, and explicit inputs only.
- GitHub CI is manual and requires explicit request.

## Dispatch and completion

Coordinating instance owns queue edits; agents report results for recording. Max model: Sol 6.1 (medium/large); Terra 6.1 (simple/bounded). Assign non-overlapping files and a separate worktree per change. Create one named Rex session per work item on its execution host, record host/session ID in the queue, and reuse panes. Parallelize independent work across hosts/instances without requiring full upfront design; track dependencies before dispatch.

Start with one heavy build per host (lightweight edits/reviews/checks may run concurrently). Default container budget: 4 CPUs / 6 GiB, 2 Bazel jobs, 1 local test, 1 graph worker (measure before increasing). Check free space before heavy work; share the bounded cache instead of keeping duplicate persistent action caches; keep active outputs disposable and preserve small reports.

Statuses: `queued`, `active`, `blocked`, `review`, `done`. Before marking `done`: review diff, run checks, preserve evidence, integrate, remove clean worktree without force, and close that item's Rex session (preserve reports first). Never delete unmerged/unrelated work, sessions, or independently managed services; remove scratch outputs only after verifying ownership and preserving reports.

## Host allocation

| Host | Assignment | Resource and transport notes |
| --- | --- | --- |
| MacBook Pro | Source edits, portable checks, producer builds, integration review | 18 GiB RAM (~241 GiB free at setup). Primary checkout is the integration point. |
| Mac mini | Shared cache, native macOS independent consumers, portable checks | 16 GiB RAM (~279 GiB free). Tailscale HTTPS shared cache with zstd: 50 GiB eviction budget, 53 GiB hard cap. |
| Azure VM | Linux-specific qualification only (Ubuntu 26.04.1 x64; deallocated) | 256 GiB XFS `/build` disk (~251 GiB free). User authorizes re-enabling when needed: prepare bounded jobs first, run one at a time, preserve reports on a Mac, clean owned state, and deallocate immediately. Does not replace Ubuntu ARM64 worker release gate. |

Host addresses, service files, and client overrides stay outside Git (ignored `.cache/shared-cache/` on both Macs; user LaunchAgents require login). Linux guests require the optional host UNIX socket relay (direct guest Tailscale routing timed out). Cache retention does not replace active outputs or SDK/package acquisition.

## Active work

_(None currently queued.)_
