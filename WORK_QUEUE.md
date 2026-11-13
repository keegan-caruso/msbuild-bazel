# Production readiness work queue

This file is the authoritative work queue. Update it when assigning work, changing
scope, finding a blocker, completing checks, or integrating a change. Keep entries
small until they are ready to execute. Completed entries may be removed or reduced
to a short result after their changes and evidence are preserved.

Execution is paused at the user's request. Do not dispatch or resume queued work
until the user resumes it. Status inspection and requested housekeeping are allowed.

## Agreed release scope

- Bazel 9.3.2 only initially; drop Bazel 8.x support and qualify later 9.x updates
  explicitly. Preserve historical measurement pins rather than relabeling evidence.
- Linux ARM64 in the qualified Ubuntu environment, with workers supported and
  enabled by default. Worker reliability is a release gate.
- Native macOS ARM64 with ordinary actions. Native Linux x64 is not a launch blocker.
- Downloaded SDKs and source-built SDK/runtime workflows are launch requirements.
  Define the exact producer, consumer, Build/test/Pack/Publish and execution
  boundaries during qualification; do not infer complete upstream parity or signing.
- Retain the graph/plugin backend, declared toolchains and explicit inputs.
- GitHub CI remains manual and requires an explicit request.

## Dispatch and completion

The coordinating instance owns queue edits; agents report results for it to record.
Use Sol 6.1 as the maximum model for medium/large work; use Terra 6.1 for simple,
bounded changes and checks. Assign non-overlapping files and a separate worktree to
each change. Create a new named Rex session for each work item on its execution
host; record the host and session ID with the assignment. Reuse panes rather than
opening a new tab for every command. Parallelize independent work across hosts and agent instances, without
requiring a complete design before starting. Track dependencies before dispatch.

Start with one heavy build per host; lightweight edits, reviews and checks may run
concurrently. Use four CPUs and 6 GiB per build container initially, two Bazel jobs,
one local test and one graph worker instance. Measure before increasing concurrency.
Check free space before heavy work. Share the bounded cache; do not retain duplicate
persistent action caches. Keep active outputs disposable and preserve small reports.

Statuses: queued, active, blocked, review, done. A passing agent report alone is not
integration. Before marking done, review the diff, run the relevant checks, preserve
evidence and integrate the change. Then verify the worktree is clean and remove it
without force, then close that work item's Rex session. Preserve the reports before
closing its terminal output. Never delete unmerged work or unrelated worktrees,
sessions or independently managed services. Remove completed
scratch outputs only after preserving useful reports and verifying ownership.

## Host allocation

| Host | Assignment | Resource and transport notes |
| --- | --- | --- |
| MacBook Pro | Source edits, portable checks, producer builds, integration review | 18 GiB RAM; approximately 241 GiB free at setup. Primary checkout is the integration point. |
| Mac mini | Shared cache, independent recovery consumers, Linux worker qualification | 16 GiB RAM; approximately 279 GiB free after authorized container reset, before new jobs. Cache eviction budget 50 GiB, hard cap 53 GiB. |

Host addresses, service files and client overrides stay outside Git. Both hosts have
ignored `.cache/shared-cache/` client configuration. Linux guests require the optional
host UNIX socket relay because direct guest Tailscale routing timed out. Native
cross-host Bazel 9.3.2 reuse and Linux curl transport passed; full Linux Bazel/MSBuild
recovery remains to be qualified. Cache retention does not replace active outputs or
SDK/package acquisition. User LaunchAgents require login.

## Ready and active work

| ID | Priority / status | Task and acceptance | Owner / host / worktree | Dependencies and evidence |
| --- | --- | --- | --- | --- |
| Q01 | P0 / review | Finish shared-cache container workflow. Verify generic guest relay with TLS and real Linux Bazel/MSBuild access; integrate launcher, tests and documentation. | Coordinator; Sol implementation and Terra review; both hosts. `/private/tmp/msbuild-cache-workflow-1113`, branch `codex/shared-cache-workflow`. | Native service and 9.3.2 cross-host tiny-action recovery passed. Focused launcher/relay controls pass. Linux curl socket transport passed; generic guest helper TLS/CAS checks passed on both hosts. Full Ubuntu worker builds remain untested. Completed setup/verification Rex sessions closed; create a new Q01 session when resuming integration. Evidence: local `/tmp/msbuild-cross-host-cache-20261113/REPORT.md`. |
| Q02 | P0 / queued | Repair acceptance fixtures first: reproduce `package_sdks` and `protocols`, update current contracts while retaining intended assertions; repair stale payload-concurrency probe and include relevant controls. | Sol 6.1; local implementation, mini Linux reproduction; worktree assigned at dispatch. | Audit wiring verified; documented legacy failures not yet reproduced in this run. Acceptance stops at first failure and feeds full/version gates. Audit worktree `/private/tmp/msbuild-cleanup-audit-1113` is read-only context, not implementation. |
| Q03 | P0 / queued | Resolve Bazel version as explicit override then repository pin; remove active generator hard-codes, record selection in workflow state and validate resume. Move active support/test matrix to 9.3.2 only. | Sol 6.1; local implementation and portable checks, mini independent consumer; worktree assigned at dispatch. | Targets include `scripts/source_runtime/linux.py`, `scripts/setup-runtime-demo.py`, pins and active matrix. Preserve historical evidence. Coordinate gate edits with Q02. |
| Q04 | P0 / queued | Make the supported Linux configuration use workers by default. Define the release gate and qualify failure recovery, bounded output/resource behavior and clean retries. | Sol 6.1; local code and mini qualified Linux runs. | Q01, Q02, Q03. Inspect active-request deadlines, output capture and publication cleanup; do not assume all audit questions are confirmed defects. |
| Q05 | P0 / queued | Specify and test concurrent project-cache publication, interruptions, eviction and corruption. Implement the supported policy without claiming cross-machine atomicity from a local lock. | Sol 6.1; local fault fixtures, independent producer/consumer on both hosts. | Q01. Existing check-then-PUT has a documented divergent-writer race. Existing transport retries and integrity checks remain in scope. |
| Q06 | P0 / queued | Qualify source-built SDK/runtime production workflows on the release baseline: declared producer handoff, consumer operations, actual tests, stopped-producer recovery and source/runtime identity. | Sol 6.1; distribute producer and consumer between hosts, one heavy job each. | Q01–Q05 as relevant. Keep full upstream parity, official signing and unsupported architectures explicit rather than implied. |
| Q07 | P1 / queued | Extract small private project/framework selection and safe-path helpers in `msbuild/graph.bzl`; preserve rule-specific actions and error context. | Terra 6.1 for bounded refactor, Sol review if scope grows; local host. | Independent of cache implementation; coordinate with any graph defaults edits in Q04. Validate analysis controls and negative-path cases. |

## Later work

| ID | Priority / status | Next decision or acceptance boundary |
| --- | --- | --- |
| Q08 | P1 / queued | Versioned distribution, consumer install/upgrade/rollback, API and cache compatibility policy. Choose packaging when release gate is stable. |
| Q09 | P1 / queued | Actionable cache/worker diagnostics, bounded retained evidence, security/update ownership and release checklist. |
| Q10 | P1 / queued | Sustained representative application and source-build trials; record peak memory, disk growth, correctness and tail latency before setting production budgets. |

## Completed setup

- Mac mini Apple containers, images and volumes reset directly by coordinator with
  user authorization; free space rose from 72 to 279 GiB. Host files were preserved.
- Native shared cache provisioned with private Tailscale HTTPS, zstd and bounded
  storage. Both hosts have private UNIX socket relays for guest transport.
- Tiny Bazel action recovered across hosts on 9.3.2 with a fresh consumer output
  base, uploads disabled and matching output digest. Namespaced project HTTP probes
  passed. This is transport evidence, not full graph qualification.
