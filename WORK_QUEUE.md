# Production readiness work queue

This file is the authoritative work queue. Update it when assigning work, changing
scope, finding a blocker, completing checks, or integrating a change. Keep entries
small until they are ready to execute. Completed entries may be removed or reduced
to a short result after their changes and evidence are preserved.

Execution resumed at the user's request. Q01 was integrated before dispatching
independent ready work across both Macs. Current work is native macOS and portable
checks: the user is preparing a Linux build server. Do not start Linux jobs; retain
existing Linux evidence and qualify the new server when requested.

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

## Ready and deferred work

| ID | Priority / status | Task and acceptance | Owner / host / worktree | Dependencies and evidence |
| --- | --- | --- | --- | --- |
| Q02a | P0 / queued | Resolve remaining native gate fixture failures: `tools.py:104` cannot rewrite copied read-only replay `NuGet.Config` (`tools/PackageSdks.cs:72`); default NuGet HTTP-cache fixture assumes a Linux XDG path on macOS. Preserve assertions, then rerun full graph acceptance and .NET checks on the composed 9.3.2 baseline. | Unassigned; no worktree/session until dispatch. | Q02/Q03 integrated. Reports below preserve failures. Affected repaired controls pass; full gates remain incomplete. |
| Q04 | P0 / queued; Linux deferred | Make supported Linux execution use workers by default; qualify failure recovery, bounded output/resources and clean retries. Inspect deadlines, output capture and publication cleanup before treating audit questions as defects. | Unassigned pending the user's Linux build server. | Q01–Q03 integrated; full native gate follow-up Q02a remains queued. No new Linux runs. |
| Q06 | P0 / queued; Linux deferred | Qualify source-built SDK/runtime production on 9.3.2: producer handoff, consumer Build/test/Pack/Publish, actual tests, stopped-producer recovery and source/runtime identity. | Unassigned pending the Linux server and worker gate. | Q01–Q05 as relevant. Preserve scope limits: no inferred whole-upstream parity, signing or unsupported architectures. |

## Completed work

Passing affected controls do not imply a passing complete release gate. Reports
retain commands, pins, worktree/session ownership and limits; task branches remain
available after clean worktree removal.

| ID | Integration / result | Evidence and limits |
| --- | --- | --- |
| Q01 | `e002504`: shared HTTPS container defaults and generic guest relay. Portable controls3, fresh Linux direct quickstart test/run and existing integration controls2 passed before Linux deferral. | `/tmp/msbuild-q01-evidence-1113/REPORT.md`; prior native cross-host tiny-action recovery `/tmp/msbuild-cross-host-cache-20261113/REPORT.md`. No complete Linux cross-host graph recovery or worker claim. |
| Q02 | `c3bc5ae` (`12f1143`): supported package-SDK/protocol/payload fixture repairs and local-cache acceptance isolation. Affected native9.3.2 controls pass; full gate passed9 slices then stopped at Q02a. | `/tmp/msbuild-q02-evidence-1113/REPORT.md`; mini `/Users/keegancaruso/q02-evidence-1113`. Mini equivalent commit `992e58b` retained after all4 file hashes matched. Native tools preserved at mini `~/.cache/msbuild-native-tools-1113`, SDK10.0.400 verified. No nested integration or complete acceptance pass. |
| Q03 | `4d23b2a` (`15e5ae2`, `25857f4`): explicit override then repository pin, recorded/resume-validated workflow selection, active9.3.2-only baseline. Native analysis25, scaffold, portable tooling and owned builds/format pass. | `/tmp/msbuild-q03-evidence-1113/REPORT.md`. Complete .NET gate retains Q02a default-cache fixture failure; Linux qualification deferred. |
| Q05 | `b360d86` (`5b921df`, `760aeeb`, `aaeb3cc`): explicit read-only consumers, serialized-publisher policy, independent-process faults, runtime policy retention and GET-only consumer preflight. Defaults remain read-write. | `/tmp/msbuild-q05-evidence-1113/REPORT.md`, `/tmp/msbuild-q05-runtime-evidence-1113/REPORT.md`. Native graph/store faults and independent mini snapshot digest pass; ProjectSync53/7skips plus targeted mode control; final composed tooling69/2skips and scaffold pass. Divergent racing HTTP writers remain unsupported; live Linux worker/source-runtime propagation deferred. |
| Q07 | `5e93290` (`9591cbe`): private graph selection/path helpers preserve rule-specific actions/errors. Native analysis31/31, scaffold, buildifier and diff checks pass. | `/tmp/msbuild-q07-analysis-rerun-1113.log`, `/tmp/msbuild-q07-check-1113.log`. No Linux or CI. |

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
