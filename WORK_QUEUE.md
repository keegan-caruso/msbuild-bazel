# Production readiness work queue

This file is the authoritative work queue. Update it when assigning work, changing
scope, finding a blocker, completing checks, or integrating a change. Keep entries
small until they are ready to execute. Completed entries may be removed or reduced
to a short result after their changes and evidence are preserved.

The local Ubuntu 26.04 / LLVM 18 producer migration is complete on the Macs;
remaining release qualification is tracked below.
The Azure Ubuntu 26.04 x64 host is deallocated. The user explicitly authorizes
re-enabling it when needed for qualification; L01–L04 no longer await resume
permission. Do not start it merely because authorization exists: prepare bounded
Linux-specific jobs first, use the mounted `/build` disk, run one job at a time,
minimize idle cost, preserve reports on a Mac, clean owned state and deallocate
after each batch. ARM64 producer qualification stays on the Macs.
The x64 host does not replace Ubuntu ARM64 qualification or a declared producer.

## Direct smoke launcher (#215)

Codex, Linux x64, worktree `restore-215`. Scaffold, 49 Bazel analysis tests, 62 source SDK controls and the managed runtime probe passed. Paired ARM64 qualification requires the stopped VMR producer and populated cache.

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
| Mac mini | Shared cache, native macOS independent consumers and portable checks | 16 GiB RAM; approximately 279 GiB free after authorized container reset, before new jobs. Cache eviction budget 50 GiB, hard cap 53 GiB. |
| Azure VM | Linux-specific qualification only; verified Ubuntu 26.04.1 x64 | 256 GiB XFS data disk is mounted and writable for `/build` qualification work (251 GiB free at preflight). Run one preprepared bounded job at a time with conservative concurrency; no general tasks or idle build servers. Preserve reports and clean up owned worktrees and processes; leave independently managed services alone. This x64 host does not replace the qualified Ubuntu ARM64 worker release gate. |

Host addresses, service files and client overrides stay outside Git. Both hosts have
ignored `.cache/shared-cache/` client configuration. Linux guests require the optional
host UNIX socket relay because direct guest Tailscale routing timed out. Native
cross-host Bazel 9.3.2 reuse and Linux curl transport passed; full Linux Bazel/MSBuild
recovery remains to be qualified. Cache retention does not replace active outputs or
SDK/package acquisition. User LaunchAgents require login.

### Retained contexts (inventory, not dispatched work)

The Nov15 audit also found independently retained local worktrees
`/tmp/msbuild-azure-setup-1115`, `/tmp/msbuild-cleanup-audit-1113` and a detached
Codex checkout, plus legacy prunable Git registrations. These are preserved,
not assigned to this migration or authorized for deletion. Unrelated Rex sessions
`update-msbuild-bazel` and `azure-linux-setup` remain open; `.playwright-mcp` and
unrelated queue history remain untouched. All migration source/catalog/fix
worktrees and task sessions were removed/closed
after PR177 integration. The ready runtime setup and frozen launcher are retained
outputs, not development worktrees. Final queue-only publication uses MacBook
`/tmp/msbuild-ubuntu26-completion-pr-1115`, Rex
`session:01a1e2e8-33f3-75a1-a666-c3f13e5ecc0f`; publication and ordered publisher cleanup evidence is tracked in `/tmp/msbuild-ubuntu26-producer-evidence-1115/COMPLETION.md`.

Retained platform pins outside this IL source-runtime migration: manual
`.github/workflows/linux.yml` Ubuntu22.04; source-built SDK10.0.100 archive
Ubuntu22.04; separate `tests/graph_build/native_aot.py` and its compiler/catalog
LLVM14. These are explicit separate scopes, not silently upgraded or newly
qualified; follow-up migrations need separate decisions. No CI is started.

## Ready and deferred work

| ID | Priority / status | Task and acceptance | Owner / host / worktree | Dependencies and evidence |
| --- | --- | --- | --- | --- |
| U26.general | done | General Apple Containers use pinned Ubuntu 26.04, SDK10.0.400/Bazel9.3.2; explicit Rosetta AMD64 and verified libarchive extraction. | Lead / MacBook; clean worktree removed before Rex `session:01a1e15c-11e9-7aa2-8651-8d840a7ca69e` closed. | PR175 reviewed/rebase-merged48f66c7. Both fresh ARM64/AMD64 sandboxed quickstart build/test/app architecture/sync pass; tooling72 tests pass2 skips. Verified local image metadata promoted; original images/services preserved. Evidence `/tmp/msbuild-ubuntu26-general-evidence-1115/REPORT.md`; Azure off. |
| U26.arm64 | done | Independently build and validate the general Ubuntu26ARM64 image on Mac mini, then promote verified image metadata without deleting old images/services. | Graph agent / Mac mini; clean worktree removed before Rex `session:01a1e15b-cebe-79fa-9c12-a2e3622674ad` closed. | Initial b349 ARM64 general image passed actual build/test/run/sync; metadata promoted mini cache, evidence `~/ubuntu26-mini-evidence-1115`. Final extractor image independently passed MacBook. Unrelated mini checkout/.DS_Store preserved. |
| U26.producer | done | Ubuntu26 ARM64 / LLVM18.1.8 IL source-runtime production and consumer identity qualified. | Graph agent / both Macs; clean implementation/mini worktrees removed before Rex `session:01a1e15e-dc68-7789-8462-767a407adb22` and `session:01a1e16b-f922-755b-b2ac-9d8ec788aa64` closed. | PR177/e378d36.194-package C/C++ probe, all3 actual native producers,631-configuration/563-compilation managed qualification and both forced consumer tests pass. Supported resume recovered an interrupted final Build; native outputs cached,563 managed misses/0hits. Source-framework172 members,649-file22MiB archive, hashes/modes, SDK-absent and missing-CoreCLR controls verified. Host frozen run.sh passes; ready product at mini `~/ubuntu26-source-runtime-product-mini-1115` retained, owned worker stopped. Full evidence `/tmp/msbuild-ubuntu26-producer-evidence-1115/FINAL.md` and verified raw export. No paired speedup, older-glibc/x64-producer/RBE or full release-parity claim. |
| U26.producer-pr | done | Focused producer implementation/current evidence integrated; historical22/14 measurements and separate SDK/NativeAOT/CI pins remain scoped. | Lead / MacBook; clean PR worktree removed before Rex `session:01a1e188-d764-7b1f-8623-369267124793` closed. | PR177 reviewed/rebase-merged e378d36;20 owned paths exactly match reviewed3dfff16. Scaffold, ArtifactTools build/format, tooling74 tests/2 skips, Mac artifacts19/2 Linux skips and Linux19/19 pass. Raw full-product evidence/launcher/archive preserved; no CI or Azure job. |
| U26.mergedusr | done | Exact merged-usr root alias normalization retains duplicate/path/link checks. | Terra / MacBook; clean worktree removed before Rex `session:01a1e17b-92d2-75a5-abf4-5f1561bfb752` closed. | a96483d/f50001b integrated through PR177. Linux19/19 regressions and actual194-package assembly pass. Evidence `/tmp/msbuild-ubuntu26-merged-usr-evidence-1115/REPORT.md`; branches retained. |
| U26.catalog | done | Official Ubuntu26 ARM64 closure with exact LLVM18/compiler-rt, GNU tools and deterministic UTC alias. | Terra / MacBook; clean worktree removed before Rex `session:01a1e15e-fff0-72a7-a554-b514b8d7aa9a` closed. | f5c869a integrated through PR177:194 archive hashes/161 canonical licenses verified,792 retained links resolved, actual C/C++ and native product builds pass. Evidence `/tmp/msbuild-ubuntu2604-research-1115/CATALOG-REPORT.md`; branch/raw reports retained. |
| U26.queue-audit | done | Published all accumulated queue history and live migration/qualification/cleanup inventory. | Lead / MacBook; clean queue worktree removed before Rex `session:01a1e18d-30c4-79fa-ba2d-cd37c72d1fa4` closed. | PR176 reviewed/rebase-merged5f1b2bb; primary fast-forwarded and exact byte comparison confirmed original authoritative queue preserved. Unrelated `.playwright-mcp` untouched. Evidence `/tmp/msbuild-ubuntu26-queue-audit-1115/REPORT.md`. Subsequent live changes remain tracked for completion evidence. |
| U26.cleanup | done | Preserved ready product/reports/branches; removed integrated worktrees before closing task sessions. | Lead + graph/Terra owners / both Macs. | All4 local source/catalog/fix/PR worktrees and mini producer worktree clean/removed, named sessions closed. Only2 owned stopped disposable probes deleted; ready stopped worker/product/run.sh/frozen rules retained. Controller4010/task caffeinate4070 exited. Unrelated services/images/worktrees and `.playwright-mcp` preserved. Final publication metadata below; Azure remains deallocated and authorized only for prepared qualification batches. |
| L01 | P0 / queued; preflight complete | Verify Azure platform/toolchain/namespaces, then qualify worker lifetime, cancellation, bounded output, retries and Bazel worker controls where feasible. | Graph agent / Azure / `/build/msbuild-qualification` public clone; Rex `session:01a1e0d9-7f36-7e72-980b-af73b7b1609f`. | Baseline `71638ef`; one bounded job, four CPUs/two Bazel jobs/one worker initially. Actual Ubuntu26.04.1 x86_64; packaged bwrap namespaces pass with AppArmor unchanged. The VM clone was prepared at `7d5acae`; current public `e378d36` contains the reviewed fixes, PR175 general Ubuntu26 and PR177 ARM64 runtime migration (earlier qualifying base `0a393a2`). VM is deallocated; the user now authorizes restart when needed for a prepared Linux qualification batch. Current-source qualification remains unrun; preserve `/build` workspace scope and deallocate after evidence/cleanup. |
| L02 | P0 / queued | Fresh-output HTTP project/action recovery, read-only consumers, interrupted/corrupt transfer and publication controls; keep Linux x64 scope explicit. | Graph agent / Azure; new named session on dispatch. | L01 bootstrap; fresh disposable producer/consumer directories, preserve exact byte/mode reports on Mac before deallocation. |
| L03 | P0 / queued | Exercise Linux-only qualification/Restore cache, seeded observations and compiler/copy boundaries with the shared ownership index. | Graph agent / Azure; new named session on dispatch. | L01 bwrap namespace capability; pinned SDK and full test_sync controls. No timestamp-based verification shortcut. |
| L04 | P0 / blocked on declared producer platform | Assess bounded source-built SDK/runtime qualification on the new platform; run portable/downloaded-SDK consumers where valid, retain declared native producer/OS/architecture boundaries. | Lead / Macs; Azure only for executable qualification. | Q06; The declared source workflow remains ARM64. Historical qualification used pinned Ubuntu22 ARM64 products; U26/PR177 completed the Ubuntu26/LLVM18 ARM64 IL runtime producer migration and local full-product/consumer validation on the Macs. Azure remains Ubuntu26 x64 without a declared x64 native producer; ARM64 results do not qualify that platform. |
| L05 | P0 / done for current bounded batch | Preserve reports on Mac, clean owned jobs/worktrees/sessions and deallocate the exact verified Azure VM; verify final power state. | Lead; Azure control plane from Mac. | L01–L04 batch completion or concrete blockers. Azure control plane confirmed `PowerState/deallocated` after reports/preflight preservation. Disks/resources retained. User now authorizes future qualification restarts when needed; keep deallocated until a bounded batch is prepared, then deallocate again. |
| Q04 | P0 / queued; scoped Linux qualification | Make supported Linux execution use workers by default; qualify failure recovery, bounded output/resources and clean retries. Portable supervision/deadline/output/cancellation changes integrated in R04; qualify them in the actual Linux/Bazel worker environment, including publication cleanup. | Azure graph agent; scoped tasks L01–L03 below; ARM64 release gate retained. | Q01–Q03 integrated; Q02a native gates pass; ordinary Ubuntu26 ARM64 worker production passes U26, while failure/cancellation/recovery qualification remains pending. New x64 controls are recorded separately from ARM64 qualification. |
| Q06 | P0 / queued; scoped Linux qualification | Qualify source-built SDK/runtime production on 9.3.2: producer handoff, consumer Build/test/Pack/Publish, actual tests, stopped-producer recovery and source/runtime identity. | Lead; scope assessment L04 below; reviewed producer platform remains required. | Q01–Q05 as relevant. U26 qualifies local Ubuntu26 ARM64 IL runtime Build/archive and actual consumer identity on9.3.2; sourceSDK/handoff/Pack/Publish/stopped-producer remote qualification remains. Preserve scope limits: no inferred whole-upstream parity, signing or unsupported architectures. |

## Completed work

Passing affected controls do not imply a passing complete release gate. Reports
retain commands, pins, worktree/session ownership and limits; task branches remain
available after clean worktree removal.

| ID | Integration / result | Evidence and limits |
| --- | --- | --- |
| Rosetta smoke | Local Apple Containers Ubuntu 22.04.5 `linux/amd64` smoke passed with Rosetta, 2 CPUs / 1 GiB: uname `x86_64`, dpkg `amd64`, `/bin/sh` ELF machine `0x003e`, exit 0. Owned container removed and dedicated Rex session closed; service and unrelated buildkit preserved. | `/tmp/msbuild-rosetta-smoke-1115`; image index `sha256:2edbbc5dc405e9612ba3584ce95480277e3eb374407b5505fe26f17df77c7dbc`, amd64 manifest `sha256:79676deb51ebb02885b0b9d33788e78a37cf1045ad79d1bb04c6a222c3556b3d`; Rex `session:01a1e13e-4cf9-77ef-9032-3ff8301a2e98`. Platform smoke only; no SDK/native compilation qualification or Azure job. |
| P01-P02 | Closed umbrella PR160 unmerged, then reviewed and merged focused PRs161–172 sequentially with the repository-required rebase strategy. Final public/primary `c3a26fd` tree equals reviewed `71638ef`; exactly12curatedcommits. | `/tmp/msbuild-focused-series-1115/REPORT.md`; allfocusedintermediatechecks pass, exacttree/lease proofs retained. Priorprimaryhistory backed up; clean12worktrees/session cleanup complete; branches preserved. NoCI. |
| H01 | Verified existing Azure qualification VM through Rex and Azure control plane; obsolete provisioning blocker superseded. Old setup worktree/session remain independently managed. | `/tmp/msbuild-linux-qualification-1115/REPORT.md`; prior setup report `/tmp/msbuild-azure-setup-evidence-1115/REPORT.md` retains historical MFA failure. Current host identity, namespace/tools and shutdown permissions checked live; L01–L05 own qualification and deallocation. |
| Policy | Azure qualification-only host policy recorded; local documentation worktree removed and Rex session closed after integration. | MacBook; worktree `/tmp/msbuild-azure-policy`; Rex `session:01a1e0d5-4877-71fb-9624-24f47ee139fc`. `git diff --check` passed; no host verification, Linux jobs or CI. |
| Q02a | PR173 (`12ff41e`): replay fixture roots and native default NuGet HTTP-cache isolation repaired; assertions retained. | `/tmp/msbuild-q02a-evidence-1115/REPORT.md`; native macOS ARM64/SDK10.0.400/Bazel9.3.2 full owned .NET gate and all17 graph acceptance slices plus native quickstart pass. Platform-specific skips remain; no Linux qualification or CI. |
| R02-R08 | `0ff6eda` through `b8cddc1`: all seven review fixes implemented, independently reviewed and integrated across both Macs; controls/docs wired. Clean worktrees and dedicated sessions removed; branches/evidence preserved. | `/tmp/msbuild-review-fixes-1115/REPORT.md`; composed owned builds/style, scaffold and affected native controls pass. Native gate failures resolved by Q02a; actual Linux qualification remains pending. No end-to-end speedup claim or CI. |
| R01 | Static deep review of `307dca0` complete; no production edits or CI. Review worktree clean and removed; dedicated local Rex session closed. | `/tmp/msbuild-deep-review-report-1113.md`; independent `/tmp/msbuild-graph-review.md` and `/tmp/msbuild-sync-review.md`. Seven ranked recommendations, refactor boundaries and validation proposals; no benchmark or new qualification claims. |
| Q01 | `e002504`: shared HTTPS container defaults and generic guest relay. Portable controls3, fresh Linux direct quickstart test/run and existing integration controls2 passed before Linux deferral. | `/tmp/msbuild-q01-evidence-1113/REPORT.md`; prior native cross-host tiny-action recovery `/tmp/msbuild-cross-host-cache-20261113/REPORT.md`. No complete Linux cross-host graph recovery or worker claim. |
| Q02 | `c3bc5ae` (`12f1143`): supported package-SDK/protocol/payload fixture repairs and local-cache acceptance isolation. Affected native9.3.2 controls pass; full gate passed9 slices then stopped at Q02a. | `/tmp/msbuild-q02-evidence-1113/REPORT.md`; mini `/Users/keegancaruso/q02-evidence-1113`. Mini equivalent commit `992e58b` retained after all4 file hashes matched. Native tools preserved at mini `~/.cache/msbuild-native-tools-1113`, SDK10.0.400 verified. No nested integration or complete acceptance pass. |
| Q03 | `4d23b2a` (`15e5ae2`, `25857f4`): explicit override then repository pin, recorded/resume-validated workflow selection, active9.3.2-only baseline. Native analysis25, scaffold, portable tooling and owned builds/format pass. | `/tmp/msbuild-q03-evidence-1113/REPORT.md`. Historical Q02a native fixture failure is resolved; Linux qualification remains pending. |
| Q05 | `b360d86` (`5b921df`, `760aeeb`, `aaeb3cc`): explicit read-only consumers, serialized-publisher policy, independent-process faults, runtime policy retention and GET-only consumer preflight. Defaults remain read-write. | `/tmp/msbuild-q05-evidence-1113/REPORT.md`, `/tmp/msbuild-q05-runtime-evidence-1113/REPORT.md`. Native graph/store faults and independent mini snapshot digest pass; ProjectSync53/7skips plus targeted mode control; final composed tooling69/2skips and scaffold pass. Divergent racing HTTP writers remain unsupported; live Linux worker/source-runtime propagation deferred. |
| Q07 | `5e93290` (`9591cbe`): private graph selection/path helpers preserve rule-specific actions/errors. Native analysis31/31, scaffold, buildifier and diff checks pass. | `/tmp/msbuild-q07-analysis-rerun-1113.log`, `/tmp/msbuild-q07-check-1113.log`. No Linux or CI. |

## Later work

| ID | Priority / status | Next decision or acceptance boundary |
| --- | --- | --- |
| Q08 | P1 / queued | Versioned distribution, consumer install/upgrade/rollback, API and cache compatibility policy. Choose packaging when release gate is stable. |
| Q09 | P1 / queued | Actionable cache/worker diagnostics, bounded retained evidence, security/update ownership and release checklist. |
| Q10 | P1 / queued | Sustained representative application and source-build trials; record peak memory, disk growth, correctness and tail latency before setting production budgets. |
| Q11 | P1 / queued | Move the project to .NET 11: select and pin the SDK/runtime release, migrate owned target frameworks and verify MSBuild API compatibility; keep bootstrap, toolchain/catalog defaults, tests and current documentation consistent. Qualify supported platforms and preserve historical measurement pins. Migration is separate from the current review fixes; release availability/selection remains to be decided. |

## Completed setup

- Mac mini Apple containers, images and volumes reset directly by coordinator with
  user authorization; free space rose from 72 to 279 GiB. Host files were preserved.
- Native shared cache provisioned with private Tailscale HTTPS, zstd and bounded
  storage. Both hosts have private UNIX socket relays for guest transport.
- Tiny Bazel action recovered across hosts on 9.3.2 with a fresh consumer output
  base, uploads disabled and matching output digest. Namespaced project HTTP probes
  passed. This is transport evidence, not full graph qualification.
