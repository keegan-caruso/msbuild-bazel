# Unchanged Serilog approval-test execution

Starting source: adapter `e1715ff`, pinned Serilog
`49b5339ce85385dc52d4d8e8f2b8308becf23506`. The selected library's native build,
mutation, relocation and standalone API comparison already pass. This slice
executes the unchanged `test/Serilog.ApprovalTests` project through Bazel on
macOS ARM64, Release/net10.0. Linux validation remains deferred.

All three tracks completed their native macOS acceptance. See [input findings](serilog-test-input-findings.md), [test action findings](test-action-findings.md), and [integrated acceptance](serilog-test-acceptance-findings.md).

## Parallel ownership

| Track | Owned change | Required evidence |
| --- | --- | --- |
| Test inputs | Evaluated compile/content/runtime inputs and exact package policy | Actual TestSDK source and selected asset roles declared; every qualified archive and payload verified; stale/missing/corrupt controls |
| Test action | Runner, Bazel test interface, preparation and result publication | Genuine VSTest execution without build/restore, exactly one non-skipped Fact, declared test data and usable failure results |
| Acceptance | Ordinary/native parity, mutations and relocation probe | Passing upstream test, intentional failures, correct invalidation sets, producer-free recovered bundles followed by actual test execution |

Shared production interfaces have one owner. Independent fixtures and ordinary
oracles may advance before integration; only integrated native evidence qualifies
this slice. Keep Git HEAD fixed during cache probes and serialize SDK builds
within each worktree. Use the pinned Nix Python interpreter explicitly.

## Acceptance boundaries

The approved text is a runtime input to the test and must be hashed and staged.
A test-data-only edit must not compile projects. A missing or mismatched approval
file must fail rather than regenerate the approved baseline. Zero discovered
tests, skipped tests and nonzero VSTest exit status are failures for this pilot.
The report must preserve the actual test name, counts and TRX outcome, including
intentional failing cases.

Compiler PathMap remains stable across workspaces. The test runner must account
for Shouldly's source-path lookup using declared runtime mapping and staged data;
changing upstream test source to find a checkout is outside this slice. Producer
source trees and build state are deleted before relocated acceptance.

Package analyzer, build, content, localized resource and runtime roles remain
explicit and narrowly qualified to measured packages. No restored asset is
silently dropped merely because the passing test did not invoke it. Full upstream
portfolio, other frameworks/platforms, arbitrary test frameworks, remote cache
and full host closure remain separate.

See [the inventory](serilog-approval-next.md) for the original package/target
inspection. New findings must distinguish ordinary results, runner prototypes
using ordinary bundles, and the final native graph-build/test integration.

## Integration review

Correctness review found and fixed two prerequisites: the SDK repository's optional
empty import glob, and graph discovery/execution losing SDK-selected reference
frameworks. The latter includes SDK-added transitive references and preserves
configured global identities. A restore regression also restored the existing
failed-restore diagnostic before framework negotiation runs. The native negative
controls require the actual Shouldly mismatch and injected-exception diagnostics;
an unrelated failing test cannot satisfy them.

The ordinary runtime prototype, actual upstream input export, selected-reference
native diamond, full upstream native acceptance and broader regressions are
recorded separately. Their elapsed times overlap parallel work and are not
comparative performance measurements. Full host closure and network isolation
remain unproven; VSTest uses localhost IPC. No Linux validation was run for these
tracks.

Final integration checks also passed:

- 20 exporter tests with the failed-restore correction integrated.
- 12 restore-semantic rejection/parity tests.
- 2 native configured-node tests: same-path red/blue identities, edge convergence,
  selected inner framework, and producer-free relocated cache recovery.
- 17 existing graph preparation checks and 3 test-data preparation checks.
- ActionRunner contract/process checks and the pinned environment scaffold check.

The native configured regression used frozen adapter `ac8f29f`; evidence is in
`/private/tmp/serilog-integrated-configured.log`. The exporter run is recorded in
`/private/tmp/final-selected-framework-exporter.log`. The unchanged upstream native
acceptance is linked above; all three tracks have concrete independent evidence.

The final full graph-cache regression also passed all 13 tests on frozen
`43d3fb5`, including package upgrades, expected action sets, deleted-base and
producer-free relocation, and missing/corrupt/stale publication guards. Report:
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/msbuild-graph-cache-10h3zxsz/probe/report.json`.
The later restore-diagnostic correction was separately covered by the 12 restore
and 20 exporter tests; it does not change successful action execution.
