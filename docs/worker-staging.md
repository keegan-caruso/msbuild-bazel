# Remove repeated worker tool staging

## Attribution

The prior staging bucket was not mainly hashing or copying project data. A
four-vCPU Linux ARM64 repeat of the 129-project shared-restore fixture attributed
**11.02 of 12.52 summed staging worker-seconds** to `Program.Real` path resolution.
It resolved **633,003 SDK file paths** (4,907 per project), then skipped them because
the SDK already existed in the compiler sandbox. Actual snapshot file operations
accounted for **0.61 summed worker-seconds**.

The broker also recreated runner/support files in every request's raw input tree.
The child already received these files at startup and never consumed those raw
copies. Most were links to cached snapshots, not repeated full byte copies;
removing them eliminates unused files and the initial verification/cache population.

## Removed work

The toolchain now emits an exact SDK/runner inventory once as a declared Bazel
tool. Its path is a shared worker startup argument, not a per-project request
argument. The broker validates inventory paths against the pinned SDK and runner
roots at startup. Subsequent requests skip these exact known tools without
filesystem resolution, digest decoding, snapshot creation, or input-path checking.
The tools are also omitted from the per-request identity hash: that identity is
scoped to a worker whose tool identity Bazel already maintains.

This follows Bazel's tool lifecycle, rather than building a second invalidation
scheme. In pinned Bazel 8.4.2,
[`WorkerFactory.validateWorker`](https://github.com/bazelbuild/bazel/blob/8.4.2/src/main/java/com/google/devtools/build/lib/worker/WorkerFactory.java#L234)
compares the current combined tool digest with the worker's original digest and
rejects changed workers. The SDK, runner/support files and inventory remain in
`ctx.actions.run(tools=...)`; none were removed from Bazel action identity.

Project inputs, reference assemblies and package payloads retain verified,
broker-owned snapshots. Previously verified bytes already reuse the bounded CAS.
These checks enforce the current immutable-input contract; disabling them would
not address the measured dominant cost. There is no SDK-path exemption for an
arbitrary source symlink: only exact startup inventory members are skipped.

The qualified platform remains Ubuntu 22.04 ARM64 with the pinned SDK. The compiler
child's read-only mounts, output restrictions, sequential protocol and existing
trusted-build-task boundary are unchanged. This does not qualify hostile in-process
MSBuild tasks or arbitrary remote execution images.

## Experiment

Baseline is `b961414` with attribution timers/counters only; optimized runs add
the inventory implementation. Both use the pinned .NET 10.0.400/Bazel 8.4.2
container, four vCPUs, 6 GiB, native Linux storage, 129 package-free projects and
shared restore. Each cohort alternates two uninstrumented and two MSBuild-profiled
cold builds, followed by two cold raw-MSBuild builds. Download/bootstrap costs are
excluded, action caches disabled, workers/outputs cold, OS page caches not flushed.
These are sequential cohorts, not randomized pairs. Startup inventory work is
included in elapsed build time and reported separately from request staging.

Reproduce with the existing `cold_profile.py` harness and
`RULES_MSBUILD_SHARED_RESTORE=1`, then run `summarize_cold_profile.py` on its evidence
directory. Worker diagnostics now distinguish tool resolution, actual snapshots,
startup tool validation, input counts, and verified/reused bytes.

## Measured result

| Metric | Baseline | Tool staging removed |
| --- | ---: | ---: |
| Cold build-action wall samples | 19.57 / 18.42 s | 17.08 / 16.84 s |
| Cold build-action mean | 18.99 s | **16.96 s** |
| MSBuild-profiled wall samples | 18.65 / 18.87 s | 17.02 / 16.75 s |
| Summed snapshot/staging worker time | 12.52 s | **1.12 s** |
| Per-request filesystem tool classification | 11.02 s | **0** |
| Startup inventory validation, summed across 4 workers | — | 0.29 s |
| Newly verified snapshot bytes | 52.43 MB | **1.86 MB** |
| Staged input file instances | 3,228 | **1,551** |
| Per-request identity work, including cleanup | 1.16 worker-s | 0.27 worker-s |

Cold action time improves **10.7%** against the fresh baseline; request staging
improves **91.1%**. The earlier uninstrumented mean was 18.83 s; the new baseline
is consistent with that result within observed variation. Raw MSBuild in the final
cohort takes 6.98 / 6.71 s (6.84 s mean), so the cold action ratio remains **2.48x**.
First-workspace startup/setup/analysis is another 4.58 s, outside the build-action
column. This is a package-free graph measurement, not an Orchard performance claim.

The removed 1,677 input instances are 13 runner/support files per project.
Their cached hardlinks represented 1.59 GB of reused logical bytes in the baseline,
not 1.59 GB of repeated disk reads. SDK membership now resolves once per worker
instead of once per project. Per-request filesystem resolution is zero; small
in-memory membership checks remain. The 0.29 worker-seconds startup cost is included
in elapsed builds, not hidden in benchmark preparation.

[Baseline evidence](evidence/worker-staging/baseline.json) and
[optimized evidence](evidence/worker-staging/removed.json) retain samples, attribution,
counts and byte totals. Full local profiles are in `artifacts/staging-baseline/`
and `artifacts/staging-removed/`.

## Remaining work worth examining

- The surviving verified inputs are project/request/import/item data, reference
  assemblies and package payloads. First-seen content is copied and checked;
  repeat content uses the private CAS. Actual snapshot file operations now total
  only **0.51 worker-seconds** on this fixture. Eliminating their verification would
  weaken the input contract for a small potential gain.
- `Program.Prepare` still copies verified source/reference files from the raw tree
  into their logical workspace positions. A direct layout or read-only hardlink
  could remove this second materialization for immutable files, with the rewritten
  project kept private. This is a candidate for package/reference-heavy graphs,
  not a measured improvement here; preparation totals only 1.35 worker-seconds.
- Bazel still supplies tool entries in WorkRequest, which the broker parses. Tool
  inventory membership checks remain in memory. Reducing protocol payloads would
  require a different Bazel/tool contract, not another filesystem cache.

The next large optimization target is still MSBuild evaluation/build execution,
not faster hashing of these now-small snapshots.

## Validation

- Same worker PID reused across source edits; changing a declared runner-support
  tool file causes a different worker PID on the next build.
- SDK/runner inventory entries outside their pinned roots fail at startup. A
  non-inventory input symlink into the SDK still rejects a forged content digest.
- Existing forged-digest/undeclared-input protocol controls pass and recover.
- Worker acceptance passes: source edits, same-size/same-time edits, compiler
  failure/recovery, declaration checks, read-only sources/undeclared host reads,
  producer deletion and relocated cache recovery, plus compilation after recovery.
- Real 16-package MTP pass/fail/recovery and package metadata/version rejection pass.
- Worker-eligible actions forced through `--strategy=MSBuildAssembly=local` succeed
  using the new startup-argument shape. The measured 129-project app prints `64`.
- `scripts/check.sh`, `scripts/check-dotnet.sh`, and `git diff --check` pass; the
  .NET suite retains its one pre-existing environment-dependent skip.

[Acceptance report](evidence/worker-staging/acceptance.json) and
[MTP report](evidence/worker-staging/mtp.json) are preserved. Full logs are local
under `artifacts/staging-removed/`. Test containers were deleted after preserving
evidence. No GitHub CI ran.
