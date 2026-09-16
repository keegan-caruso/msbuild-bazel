# Local MVP release sign-off

Release: **v0.1.0-mvp.1**, an experimental source release for the frozen local
macOS ARM64/Nix Build/Test contract. The [installation and adoption guide](local-mvp-release.md)
provides supported invocations, artifact formats, compatibility policy and limits.

## Candidate and evidence applicability

The full release rerun measures merged `main` at
`73109f160839e25f1be3f8212e07c3deb0dce727` (PR #67 followed by PR #68).
Release packaging changes documentation and adds reproduction scripts only;
production tools, rules, tests, pins and the preparation budget remain identical.
The release provenance asset binds the final Git revision and source archive to
that measured implementation. Do not relabel old experiments as new reruns.

A new unsynchronized worktree and package cache were used under `/private/tmp`.
The run created new `DOTNET_CLI_HOME`, NuGet HTTP cache, output and disk-cache
state. Ambient HOME and the existing system Nix store/daemon remained available.
This is fresh project/tool acquisition on the supported host, not a fresh OS or
empty-store installation benchmark. The acquisition receipt records the SDK,
engine, OS build, upstream archive and package hashes, and Nix closure identities.

The supported combination remains macOS 27.0 (26A428), ARM64, Nix SDK 10.0.400,
runtime 10.0.11, MSBuild 18.9.6.38015, Python 3.13.9 and Nixpkgs Bazel 8.4.2.
Serilog is pinned to `49b5339ce85385dc52d4d8e8f2b8308becf23506` with explicit
Release/net10.0 selection. No GitHub CI was dispatched.

## Current qualification results

All **99 correctness cases** pass:

| Probe | Passing cases | Raw path under qualification state |
| --- | ---: | --- |
| Reuse/corruption/publication/concurrency | 17 | `r/report.json` |
| Consumer invalidation | 8 | `i/report.json` |
| Discovery contract | 27 | `d/report.json` |
| Serilog discovery | 15 | `sd/report.json` |
| Serilog reuse/recovery | 2 | `sr/report.json` |
| Serilog library mutations/recovery | 9 | `l/report.json` |
| Approval tests and failure controls | 5 | `t/report.json` |
| Package/restore mutations | 9 | `pk/report.json` |
| Fresh fallback | 2 | `f/report.json` |
| Lifecycle rejection | 4 | `lifecycle/report.json` |
| Prior-controller upgrade and native execution | 1 | `u/report.json` |

The owned .NET build/style checks (including five enforcement tests), ActionRunner
contract tests, 67 preparation tests, 21 graph/schema tests, two tool-output
tests, 13 Starlark/repository tests and five generated-extension tests pass.
Core Starlark coverage also executes the core and extension Bazel analysis tests.

### Frozen preparation budget

Five interleaved fresh/reuse pairs per workload follow separate seed and warm-up
runs. Times include lease teardown and final verification. Both original limits
remain unchanged: median reuse/fresh ≤ 1.0 and median reuse ≤ 5 seconds.

| Workload | Fresh median, s | Reuse median, s | Reduction | Gate |
| --- | ---: | ---: | ---: | --- |
| small | 2.292 | 1.522 | 33.6% | Pass |
| serilog | 2.221 | 1.774 | 20.1% | Pass |

The budget SHA-256 remains
`c89f378450e1d7196ce30931e7c45990d7a5511c63bf431d39b6299cec0f84c1`.

### End-to-end Build/Test

All 40 samples pass their expected compiler/action work sets and execute exactly
one real approval test. Five repetitions per state/system, with alternating order.
The table reports median command-pipeline seconds: export + preparation + build
+ actual test. Acquisition, restore, baseline warm-up, assertions, evidence copying
and shutdown are excluded and retained separately in the raw workflow timings.
Phase medians need not sum to the median total. Test preparation remains fresh.

| State | System | Export | Prepare | Build | Test | Total, s |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| fresh | MSBuild | — | — | 0.842 | 0.682 | 1.533 |
| fresh | Adapter | 0.467 | 2.998 | 7.322 | 1.632 | 12.496 |
| unchanged | MSBuild | — | — | 0.673 | 0.653 | 1.323 |
| unchanged | Adapter | 0.470 | 2.657 | 0.513 | 1.585 | 5.250 |
| sourceEdited | MSBuild | — | — | 0.692 | 0.668 | 1.365 |
| sourceEdited | Adapter | 0.478 | 2.679 | 2.041 | 1.531 | 6.711 |
| recovered | MSBuild | — | — | 0.834 | 0.682 | 1.525 |
| recovered | Adapter | 0.510 | 3.020 | 4.170 | 1.641 | 9.379 |

Unchanged Build/Test is **3.97× the ordinary MSBuild time** on this
small graph. Preparation improvements are not an end-to-end speedup claim.
Recovery is not a speed-ratio comparison: MSBuild rebuilds after output deletion
at the same path, while the adapter deletes its producer, relocates, restores both
build bundles from disk cache and forces the actual test.

Runs were serial; interactive host load, filesystem caches and the system Nix
store remain uncontrolled/shared. Bazel trace analysis/execution events overlap
and are not added to command wall times. This rerun is not an interleaved comparison
against the earlier PR #67 implementation; historical medians do not establish a
causal before/after speedup.


## Adoption assessment

The useful behavior is project-level scheduling, explicit input validation,
unchanged preparation reuse and producer-free local disk-cache recovery while
preserving the selected SDK/MSBuild semantics. The small two-project approval
workload still pays export, materialization, Bazel and test-launch overhead;
this release does not establish a net Build/Test speed advantage over MSBuild.
Larger native graphs and aggregate memory remain unmeasured.

Integration requires a separate restore/acquisition step, explicit framework and
configuration, owned source/package/state directories, prepared graph generation,
a pinned toolchain and consumption under the preparation lease. Explicit Test
requests use fresh preparation. A cached test result does not count as recovered
execution; the qualification forces the real approval test and checks its TRX.

The optional protected-store and content-refresh results in
[incremental preparation findings](incremental-preparation-findings.md) retain
their original evidence and trust conditions. They do not change the default
release gate or grant general test-preparation reuse. Their production code is
identical to the merged implementation; prior raw evidence is included separately.

## Known failure and scope dispositions

The broader implicit-framework managed-package replay case still fails with
**MSB4252**, across four PrivateAssets modes. The request selects Release and
`IsGraphBuild=true` without an explicit `TargetFramework`. The unchanged baseline
reproduces it and generates the same staged files. This is retained as a known
failure, not a passing aggregate package suite. Explicit Release/net10.0 Serilog
qualification is the release boundary. Broader configured-graph and package work
remains with [#8](https://github.com/keegan-caruso/msbuild-bazel/issues/8),
[#28](https://github.com/keegan-caruso/msbuild-bazel/issues/28) and
[#30](https://github.com/keegan-caruso/msbuild-bazel/issues/30).
See the [incremental findings](incremental-preparation-findings.md) and
[earlier engine findings](tool-input-findings.md).

An audit of all **53 deferred issue links** in the frozen support contract found
them open. Their acceptance criteria remain unchanged. The release does not
complete the broader preparation umbrella, compile/runtime boundary, native
scale, platform/version matrix, arbitrary NuGet, Clean/Rebuild, Pack/Publish,
IDE, remote-cache or remote-execution work. The audit receipt preserves every
issue title, URL and observed state.

## Reproduction and evidence

The committed [evidence index](local-mvp-signoff-evidence.json) records counts
for each probe, individual measured samples, the recomputed budget result and raw hashes.

Run `bash scripts/qualify-local-mvp.sh /private/tmp/rq` inside the pinned Nix
shell from the release Git checkout. The new directory must not exist. The
script executes gates serially, retains failure logs and stops at the first
failure; the preparation thresholds are not adjusted to obtain a pass.

Release assets contain the source tarball, `qualification-evidence.zip`,
`evidence-manifest.json`, `release-provenance.json` and `SHA256SUMS`. The evidence
ZIP contains the exact reports, logs, TRX, trace profiles, acquisition receipt,
commands, upgrade control and source-delivery check. Its embedded manifest hashes
each file. Generated source/tool/cache payloads are omitted. Historical #68
evidence is explicitly labeled, including the broader package failure.

The prior-controller upgrade control starts with an actual pre-#68 generation,
requires a `request-changed` miss, regenerates preparation and executes two native
project actions with an empty disk cache. The result must print
`mvp-calibration`. Controller and checkout/tool identities differ; this is an
upgrade rejection/recovery test, not an isolated single-input experiment.

## Delivery check and sign-off

The source candidate tarball was extracted into a new `/private/tmp/rm` directory.
The documented pinned-tool installation/checks, all five approval-test/recovery
cases, and cold followed by unchanged reusable library Build passed. The second
library preparation reports `reused=true`, `reason=unchanged`, with no discovery;
both Bazel commands completed successfully. Final documentation changes do not
change the tested production files or reproduction scripts. The delivery receipt
binds the exact smoke archive, script, report and final source comparison.

All release gates in #65 are satisfied for the frozen scope:

- [x] #63 support boundary and invocation contract retained.
- [x] #5 predeclared numeric budget retained unchanged.
- [x] #6 invalidation, corruption, concurrency and recovered execution rerun;
  accepted RUL-6 implementation revision is an ancestor.
- [x] #7 preparation gate passes; complete Build/Test costs and limits reported.
- [x] #64 pinned acquisition, rules, Build/Test, mutations and recovery rerun.
- [x] Installation, schema and cache compatibility instructions verified.
- [x] Adoption report and reproducible evidence prepared.
- [x] Version `v0.1.0-mvp.1` selected for source delivery with checksummed evidence.
- [x] All 53 deferred issue links audited without closing or weakening them.

Gate decision: ready for the experimental local release. The GitHub release and
its provenance asset record the final tag/commit and delivered artifact hashes;
#65 closes only after publication and verification. The known broader failure and
end-to-end overhead remain part of the release assessment.
