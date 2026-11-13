# Production readiness work queue

This file is the authoritative work queue. Update it when assigning work, changing
scope, finding a blocker, completing checks, or integrating a change. Keep entries
small until they are ready to execute. Completed entries may be removed or reduced
to a short result after their changes and evidence are preserved.

Execution resumed at the user's request. Verify both hosts and integrate Q01 before
dispatching independent ready items; preserve existing work and use the shared cache.
The user is preparing a Linux build server: focus current work on native macOS and
portable checks. Do not start Linux jobs; preserve existing Linux evidence and leave
new Linux qualification pending the server.

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
| Mac mini | Shared cache, native macOS independent consumers; Linux qualification deferred | 16 GiB RAM; approximately 279 GiB free after authorized container reset, before new jobs. Cache eviction budget 50 GiB, hard cap 53 GiB. |

Host addresses, service files and client overrides stay outside Git. Both hosts have
ignored `.cache/shared-cache/` client configuration. Linux guests require the optional
host UNIX socket relay because direct guest Tailscale routing timed out. Native
cross-host Bazel 9.3.2 reuse and Linux curl transport passed; full Linux Bazel/MSBuild
recovery remains to be qualified. Cache retention does not replace active outputs or
SDK/package acquisition. User LaunchAgents require login.

## Ready and active work

| ID | Priority / status | Task and acceptance | Owner / host / worktree | Dependencies and evidence |
| --- | --- | --- | --- | --- |
| Q01 | P0 / done | Shared-cache guest launcher/relay integrated as `e002504`; portable controls (3), Linux public quickstart test/run with real graph execution, cache HTTPS access and integration controls (2) passed. | Coordinator; clean dedicated worktree removed; both Q01 Rex sessions closed after preserving evidence. | Evidence `/tmp/msbuild-q01-evidence-1113/REPORT.md`; scope in `docs/support.md`. Linux stopped-producer cross-host recovery and workers remain unqualified. |
| Q02 | P0 / done (scoped repairs) | Package SDK, protocol archive and payload fixture repairs integrated as `c3bc5ae` (`12f1143`); affected native9.3.2 controls pass. | Sol implementation, lead review; both clean worktrees removed without force and Q02 sessions closed. Mini retained equivalent commit `992e58b` after all4 file SHA256 matched integrated content. | Full acceptance passed9 slices then independent `tools.py:104` read-only replay `NuGet.Config` failure; no complete gate pass or nested integration. Local report `/tmp/msbuild-q02-evidence-1113/REPORT.md`; mini verified reports `/Users/keegancaruso/q02-evidence-1113`; SDK/tools preserved at mini `~/.cache/msbuild-native-tools-1113` (SDK10.0.400 verified). Interrupted Linux run preserved, no qualification. |
| Q02a | P0 / queued | Resolve remaining native gate fixture failures: `tools.py:104` cannot rewrite copied read-only replay `NuGet.Config` (`tools/PackageSdks.cs:72`); default NuGet HTTP-cache fixture assumes Linux XDG path on macOS. Preserve intended assertions, then rerun full graph acceptance and .NET checks on current9.3.2 composition. | Unassigned; no worktree/session until dispatch. | Q02/Q03 integrated. Evidence in Q02 and Q03 reports; targeted repaired controls pass, full gates remain incomplete. Linux deferred. |
| Q03 | P0 / done | Bazel selection and active 9.3.2-only baseline integrated as `4d23b2a` (commits `15e5ae2`, `25857f4`); workflow state validates resume identity. | Sol implementation; clean worktree removed and Q03 Rex session closed after preserving reports. | Native analysis 25/25, execution requirements, scaffold, portable tooling/bootstrap and owned build/format checks pass. Full .NET gate retains independent macOS default NuGet-cache fixture failure (Linux XDG path assumption); explicit/disposable cache controls pass. Evidence `/tmp/msbuild-q03-evidence-1113/REPORT.md`. Linux qualification deferred pending new server. |
| Q04 | P0 / queued | Make the supported Linux configuration use workers by default. Define the release gate and qualify failure recovery, bounded output/resource behavior and clean retries. | Sol 6.1; local code and mini qualified Linux runs. | Q01, Q02, Q03. Inspect active-request deadlines, output capture and publication cleanup; do not assume all audit questions are confirmed defects. |
| Q05 | P0 / review | Specify and test concurrent project-cache publication, interruptions, eviction and corruption. Implement the supported policy without claiming cross-machine atomicity from a local lock. | Lead; native/portable fault fixtures in `/private/tmp/msbuild-q05-cache-policy-1113` (`codex/q05-cache-policy`), MacBook Rex `session:01a1d6f1-2be6-7046-b4c1-da341dc399d1`. No Linux jobs; cross-host Linux controls deferred. Native mini probe session `session:01a1d6f7-3b35-70a0-a4cd-8049b0bd3861`: fresh read-only fetch after publisher exit matches SHA256. Local publication/graph HTTP fault controls,53 ProjectSync checks (7Linux skips), targeted environment hiding, builds/style/scaffold pass. Added publication/fault controls to acceptance. Review found source-runtime propagation gap; bounded fix in `/private/tmp/msbuild-q05-runtime-policy-1113` (`codex/q05-runtime-policy`), Rex `session:01a1d6fd-ac3f-74e9-84af-4496dcd2f6b4`, portable-only. | Q01. Existing check-then-PUT has a documented divergent-writer race. Existing transport retries and integrity checks remain in scope. |
| Q06 | P0 / queued | Qualify source-built SDK/runtime production workflows on the release baseline: declared producer handoff, consumer operations, actual tests, stopped-producer recovery and source/runtime identity. | Sol 6.1; distribute producer and consumer between hosts, one heavy job each. | Q01–Q05 as relevant. Keep full upstream parity, official signing and unsupported architectures explicit rather than implied. |
| Q07 | P1 / done | Private graph selection/path helpers integrated as `5e93290` (`9591cbe`); rule-specific actions/errors and source-path behavior preserved. | Terra implementation, lead review; clean worktree removed and session closed after evidence preservation. | Native macOS / Bazel9.3.2 analysis31/31, scaffold, buildifier and diff checks pass. Evidence `/tmp/msbuild-q07-analysis-rerun-1113.log`, `/tmp/msbuild-q07-check-1113.log`. No Linux/CI. |

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
