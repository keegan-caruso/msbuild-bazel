# Unchanged Serilog approval-test execution

Starting source: adapter `e1715ff`, pinned Serilog
`49b5339ce85385dc52d4d8e8f2b8308becf23506`. The selected library's native build,
mutation, relocation and standalone API comparison already pass. This slice
executes the unchanged `test/Serilog.ApprovalTests` project through Bazel on
macOS ARM64, Release/net10.0. Linux validation remains deferred.

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
