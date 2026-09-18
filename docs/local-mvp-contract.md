# Local Build/Test MVP support contract

This document preserves the earlier experiment/release contract. Current production
entry points are [the .NET native workflow](native-workflow.md) and
[.NET preparation](python-removal.md#step-2-net-fresh-preparation). Python commands
here remain available only to reproduce historical tests and measurements.

Status: frozen scope and acceptance contract for [#63](https://github.com/keegan-caruso/msbuild-bazel/issues/63).
Reviewed 2026-09-15 against candidate source
`498114a4b67ba56682b93fb6a6f98d82d1b2acaf`. This records the intended
qualification boundary. The candidate includes the changes in this commit;
the evidence manifest binds its patch and input identities. The subsequent
[v0.1.0-mvp.1 release](local-mvp-release.md) retains these scope boundaries.

## Candidate and acquisition

- Native macOS ARM64, local execution and local disk cache. Candidate host:
  macOS 27.0 (26A428). Use an unsynchronized local checkout, source and cache;
  File Provider-managed directories are outside this qualified storage mode.
- On macOS, the action scratch path must fit within 208 UTF-8 bytes; a longer
  path is rejected with a shorter-output-base diagnostic. Use a short Bazel
  output base. See the [measured runtime path boundary](local-mvp-path-findings.md).
- The default `nix develop` environment from the candidate's `flake.lock`:
  SDK 10.0.400, bundled runtime 10.0.11, Nixpkgs Bazel 8.4.2.
  Nixpkgs' patched Bazel is a distinct distribution from the official binary.
- SDK Nixpkgs revision: `42f17a57f4f6e33b3de3dca0a2a5ea5233169d02`.
  Bazel Nixpkgs revision: `74c7dbb8e8adc9fdd3e734d7fd85f36f5421a2f9`.
- Observed engine: MSBuild `18.9.6.38015` (`18.9.6+14fbf8d52`), SDK commit
  `14fbf8d527`, runtime commit `e2f47b0110`, Python 3.13.9 and
  `bazel 8.4.2- (@non-git)`. Acquisition used Nix 2.35.2 and the locked default
  shell; the SDK resolves to the exact path in `tools/discovery_contract.py`.
  Preserve `flake.lock`, resolved store paths and native closure in evidence.
- Use the repository wrappers. `scripts/setup.sh` currently pins Linux archives;
  it is not this candidate's macOS installation path. Alternate SDKs, named Bazel
  matrix shells and other acquisition distributions need separate qualification.

## Workload and operations

Use Serilog revision `49b5339ce85385dc52d4d8e8f2b8308becf23506`, its
library and unchanged approval-test project, Release and the selected net10.0
inner build. Preserve authored framework declarations, signing, imports,
generators, package inputs and approved API text. Supporting fixtures cover
discovery, configured edges and dependency replay; they do not expand the
supported application portfolio.

| Operation | Candidate policy |
| --- | --- |
| Fresh export and preparation | Selected restored inputs and configuration; fail on invalid inputs |
| Reusable preparation | Opt-in RUL-5/RUL-6 build-only eligibility, default environment and pinned tools |
| Build | Selected generated graph with declared SDK, package and dependency payloads |
| Test | Unchanged approval test with actual VSTest execution; explicit test requests use fresh preparation |
| Disk-cache recovery | Same supported host; relocated consumer with producer removed, followed by actual execution |
| Preparation-cache relocation | Moving its cache/discovery root or changing host/boot requires fresh qualification |
| Clean/Rebuild and Pack/Publish | No such operation in the generated project-rule interface; arbitrary shell commands passed after `--` are caller commands, not supported MSBuild lifecycle operations |
| Solution/custom-SDK entry points | Outside reusable discovery eligibility; qualified fresh materialization remains limited to the selected SDK-style project graph |

Build/Test support does not grant test-preparation reuse. Unsupported reuse
requests must take the existing fresh path and must never receive a reuse
certificate merely because fresh preparation succeeds.

### Invocation and operation audit

Acquire the default locked shell in a local checkout with
`nix --extra-experimental-features 'nix-command flakes' develop`. Build
GraphExport, EvaluationProbe, ReplayPlugin and ActionRunner with
`bash scripts/dotnet.sh build tools/<name> -c Release --nologo`.
Restore the selected project into an explicitly owned `.nuget/packages` path,
including an empty directory for package-free fixtures.

Reusable Build entry point:

```sh
python3 tools/preparation_reuse.py --workspace <restored-source> \
  --state <owned-local-cache> --output <new-consumer> --entries <entries.json> \
  -- <pinned-bazel> build //:all
```

Entries contain workspace-relative project paths and exactly
`Configuration=Release`, `TargetFramework=net10.0`. All owned paths must be
disjoint. The command executes under the retained lease.

For fresh preparation, GraphExport accepts `--request <request.json>` under
the versioned [graph interface](graph-export-contract.md), and
`python3 tools/prepare_graph.py --workspace <source> --manifest <graph.json>
--output <new-consumer> [--tests <tests.json>]` materializes it. Test declarations
are explicit; invoke the generated test target and force test execution after
recovery with `--nocache_test_results`. Use the pinned approval harness in the
qualification protocol to retain the exact test declaration and target.

The audited `prepare_graph._prepare` rejects unsupported configuration before
creating the consumer, including Debug. The project runner uses a fixed Build
target set; no Clean, Rebuild, Pack or Publish selector is exposed by the rule.
`bazel clean` clears Bazel-owned output state; it is not MSBuild Clean or a
preparation-cache purge. No cache garbage-collection command is supported.
Historical `tools/adapter.py` exposes only its fixture-specific restore,
baseline and project operations and rejects other operation names; it is not
the MVP's Serilog entry point.

## Oracles and required controls

- The approval test must execute exactly
  `ApiApprovalTests.PublicApi_Should_Not_Change_Unintentionally`, with one
  passing Fact. Zero discovered tests and a cached test result do not count as
  recovered execution. Preserve TRX and standard Bazel test outputs.
- Retain the recovered-library logging/consumer oracle as well as API approval.
  Compare ordinary MSBuild and adapter configuration, outputs, signing and
  reference/runtime identities using the existing Serilog harnesses.
- Record expected and observed project-action sets for cold, unchanged,
  library-source, test-source, test-data, import, package and configuration edits.
  Test-data-only edits must not cause project compilation; recovered Build
  bundles must be followed by forced real tests.
- Distinguish cold preparation, unchanged eligible reuse, invalidated
  preparation, unchanged Bazel actions, empty disk cache and recovered disk
  cache. Record server state, restore/setup cost and package-cache state.
- Qualify source additions/removals, optional imports, reference metadata,
  restore/package changes, missing/corrupt state, interrupted publication,
  concurrent consumers and producer-free relocation under the same candidate.
- Verify artifact/schema/request identity and upgrade invalidation. Preserve
  the input-view lease through consumption; a saved validation report is not
  authority to reuse mutable discovery state later.

## Existing evidence and remaining release gates

The subsequent [performance qualification](local-mvp-performance-findings.md)
and [clean-candidate qualification](local-mvp-release-qualification.md) now record
passing evidence for #7 and #64. The frozen boundaries and budget below are
unchanged; the [release sign-off](local-mvp-signoff.md) records #65 delivery.

[RUL-6](https://linear.app/rules-msbuild/issue/RUL-6/reuse-and-safely-publish-unchanged-export-and-preparation)
is Done and [PR #4](https://github.com/keegan-caruso/msbuild-bazel/pull/4)
merged as `c5934ce8e54dac12bdfc49996c3043303a50cdc2`, an ancestor of this
candidate. Its implementation prerequisite is present.

- [Preparation reuse](preparation-reuse-findings.md): selected native recovery,
  publication, corruption and concurrent-consumer evidence; broader #6 matrix
  is covered by the [candidate correctness findings](local-mvp-correctness-findings.md).
- [Rule toolchain integration](rule-toolchain-findings.md): records 17 native
  reuse cases and fresh test-request fallback after SDK-input integration.
- [SDK refresh](sdk-upgrade-findings.md): selected 10.0.400 validation. Historical
  10.0.100 results are not same-toolchain release evidence.
- [R01 baseline](starlark-core-findings.md),
  [selected R02–R04 gates](r02-r04-validation-findings.md),
  [Serilog library](r04-integration-findings.md) and
  [approval tests](serilog-test-acceptance-findings.md): accepted bounded slices;
  rerun applicable gates for the frozen combination.
- [Discovery contract](discovery-contract.md) defines reusable input eligibility.
  [Historical performance](serilog-performance-findings.md) reports overhead on
  the small graph; it is not the new preparation-performance acceptance budget.

## Delivery order and freeze conditions

The [calibration and correctness protocol](local-mvp-qualification-plan.md)
records the host preflight, measurement design and remaining native matrix.
Nix acquisition and toolchain checks pass. The
[calibration findings](local-mvp-calibration-findings.md) and
[numeric budget](local-mvp-preparation-budget.json) fix the metric, five
repetitions per mode, median ratio limit of 1.0 and absolute limit of 5.0s
for each workload. Initial calibration failed the ratio limit; subsequent
[qualification](local-mvp-performance-findings.md) passed after optimization.
The [release rerun](local-mvp-signoff.md) retains the same thresholds.

1. **#63:** complete exact runtime/engine inventory, supported invocation and
   exposed-operation audit; resolve every entry-point/lifecycle disposition.
2. **#5 / RUL-7:** calibrate fresh versus reused preparation with controlled
   caches and ordinary MSBuild comparisons. Declare the numeric budget,
   repetitions and comparison statistic before qualification. No threshold is
   chosen after a qualification failure; the linked budget is declared before #7.
3. **#6 / RUL-8:** qualify the complete invalidation/recovery matrix. This can
   proceed independently of calibration once scope is fixed.
4. **#7 / RUL-9:** measure against the predeclared budget after #5 and #6.
   Report preparation work avoided and end-to-end costs separately.
5. **#64:** qualify clean acquisition, rule gates, Build/Test and recovery on the
   same candidate after #63 and #6. A new candidate needs an explicit evidence
   applicability review.
6. **#65:** retain evidence, installation/invocation instructions, compatibility
   policy and adoption report; record version/artifact and complete release
   sign-off before publishing.

The six issues are the `MVP: local Build/Test` milestone within the 61-item
[GitHub board](https://github.com/users/keegan-caruso/projects/1).
## Deferred work

These issues retain their original criteria. This contract does not complete
their broader portfolio work:

- Configured graphs and solution/custom-SDK entry points: [#8](https://github.com/keegan-caruso/msbuild-bazel/issues/8), [#22](https://github.com/keegan-caruso/msbuild-bazel/issues/22), [#57](https://github.com/keegan-caruso/msbuild-bazel/issues/57).
- Platforms: [#51](https://github.com/keegan-caruso/msbuild-bazel/issues/51), [#52](https://github.com/keegan-caruso/msbuild-bazel/issues/52), [#53](https://github.com/keegan-caruso/msbuild-bazel/issues/53), [#54](https://github.com/keegan-caruso/msbuild-bazel/issues/54), [#55](https://github.com/keegan-caruso/msbuild-bazel/issues/55), [#56](https://github.com/keegan-caruso/msbuild-bazel/issues/56), [#59](https://github.com/keegan-caruso/msbuild-bazel/issues/59), [#60](https://github.com/keegan-caruso/msbuild-bazel/issues/60), [#61](https://github.com/keegan-caruso/msbuild-bazel/issues/61), [#62](https://github.com/keegan-caruso/msbuild-bazel/issues/62).
- Coverage: [#23](https://github.com/keegan-caruso/msbuild-bazel/issues/23).
- Tasks, package consumers, versioning and Clean/Rebuild: [#10](https://github.com/keegan-caruso/msbuild-bazel/issues/10), [#24](https://github.com/keegan-caruso/msbuild-bazel/issues/24), [#25](https://github.com/keegan-caruso/msbuild-bazel/issues/25), [#26](https://github.com/keegan-caruso/msbuild-bazel/issues/26), [#27](https://github.com/keegan-caruso/msbuild-bazel/issues/27).
- Restore, publishing, runtime closure and Native AOT: [#11](https://github.com/keegan-caruso/msbuild-bazel/issues/11), [#12](https://github.com/keegan-caruso/msbuild-bazel/issues/12), [#28](https://github.com/keegan-caruso/msbuild-bazel/issues/28), [#29](https://github.com/keegan-caruso/msbuild-bazel/issues/29), [#30](https://github.com/keegan-caruso/msbuild-bazel/issues/30), [#31](https://github.com/keegan-caruso/msbuild-bazel/issues/31), [#32](https://github.com/keegan-caruso/msbuild-bazel/issues/32).
- Compile boundaries and scale: [#34](https://github.com/keegan-caruso/msbuild-bazel/issues/34), [#35](https://github.com/keegan-caruso/msbuild-bazel/issues/35), [#36](https://github.com/keegan-caruso/msbuild-bazel/issues/36); the full preparation umbrella [#33](https://github.com/keegan-caruso/msbuild-bazel/issues/33).
- Web, desktop, languages and Aspire: [#14](https://github.com/keegan-caruso/msbuild-bazel/issues/14), [#15](https://github.com/keegan-caruso/msbuild-bazel/issues/15), [#16](https://github.com/keegan-caruso/msbuild-bazel/issues/16), [#37](https://github.com/keegan-caruso/msbuild-bazel/issues/37), [#38](https://github.com/keegan-caruso/msbuild-bazel/issues/38), [#39](https://github.com/keegan-caruso/msbuild-bazel/issues/39), [#40](https://github.com/keegan-caruso/msbuild-bazel/issues/40).
- Remote caching/execution: [#17](https://github.com/keegan-caruso/msbuild-bazel/issues/17), [#18](https://github.com/keegan-caruso/msbuild-bazel/issues/18), [#41](https://github.com/keegan-caruso/msbuild-bazel/issues/41), [#42](https://github.com/keegan-caruso/msbuild-bazel/issues/42), [#43](https://github.com/keegan-caruso/msbuild-bazel/issues/43), [#44](https://github.com/keegan-caruso/msbuild-bazel/issues/44).
- IDE/design-time and runtime expansion: [#19](https://github.com/keegan-caruso/msbuild-bazel/issues/19), [#20](https://github.com/keegan-caruso/msbuild-bazel/issues/20), [#45](https://github.com/keegan-caruso/msbuild-bazel/issues/45), [#46](https://github.com/keegan-caruso/msbuild-bazel/issues/46), [#47](https://github.com/keegan-caruso/msbuild-bazel/issues/47).
- Full dispositions, multiple versions, Bazelisk and adoption: [#21](https://github.com/keegan-caruso/msbuild-bazel/issues/21), [#48](https://github.com/keegan-caruso/msbuild-bazel/issues/48), [#49](https://github.com/keegan-caruso/msbuild-bazel/issues/49), [#50](https://github.com/keegan-caruso/msbuild-bazel/issues/50), [#58](https://github.com/keegan-caruso/msbuild-bazel/issues/58).

Individual links and retained scope are in the
[parent scope issue](https://github.com/keegan-caruso/msbuild-bazel/issues/63).
GitHub CI remains manual-only and requires an explicit request.

## PR review follow-up

[Review fixes and rerun results](local-mvp-review-findings.md) strengthen the
qualification harnesses and preserve the initial evidence separately.
