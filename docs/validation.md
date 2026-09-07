# Adapter validation strategy

This document maps Bazel's testing facilities to the MSBuild adapter's validation
contract. It is a strategy and evidence index, not a Bazel certification or a new
passing test result. Existing findings retain their recorded platform, fixture
and toolchain scope. The current experimental pins are Bazel 8.4.2 and .NET SDK
10.0.100; additional versions require separate evidence. The original strategy was reconciled against main at `c81d4ca`. The added
[R01 baseline findings](starlark-core-findings.md) record subsequent implementation
and commands separately from that historical checkpoint. Follow the [active platform scope](platform-validation-scope.md): the broader
acceptance lane is native macOS ARM64, with local Linux ARM64 container evidence
for the Starlark baseline. Further Linux x86-64 CI remains deferred. Earlier Linux results retain their original revision and scope.

## Test layers

| Layer | Facility and intended use | Repository status |
| --- | --- | --- |
| Starlark quality | Pinned [Buildifier](https://github.com/bazel-contrib/buildtools/blob/main/buildifier/README.md) formatting/lint checks and Skylib unit tests for substantial pure helper logic. | Implemented by `scripts/check.sh`; pinned Buildifier acquisition and scope are in the [baseline findings](starlark-core-findings.md). |
| Generated workspaces and repositories | Load and analyze generated BUILD/MODULE files with Bazel; exercise SDK/runtime repository rules in fresh workspaces. | Existing probes exercise baseline workspaces; focused generation and repository-rule gates are specified below. |
| Rule analysis | [Bazel analysis tests](https://bazel.build/rules/testing), using Skylib, inspect registered actions, inputs, outputs, providers and expected analysis failures without running MSBuild. | Ten Skylib analysis tests cover `bazel/msbuild.bzl` and `bazel/graph.bzl` through `//tests/starlark:core`. Ten additional `//tests/starlark:extensions` tests cover package/configuration inputs, `graph_test.bzl` runfiles/policy and expected failures; see [R02–R04 qualification](r02-r04-validation-findings.md). |
| Real build integration | [rules_bazel_integration_test](https://github.com/bazel-contrib/rules_bazel_integration_test) can run fixture workspaces against selected Bazel versions. | Candidate framework for a future pinned version matrix; migration is not required to retain the current acceptance coverage. Current Python probes already invoke real Bazel and remain the behavioral acceptance source. |
| Test execution contract | The [Bazel Test Encyclopedia](https://bazel.build/reference/test-encyclopedia) defines the environment for tests run by Bazel. | The [native VSTest rule](test-action-findings.md) runs through `bazel test` with declared runfiles and standard result outputs. The outer Python harness runs outside Bazel; full language-independent test-environment compliance is not claimed. |
| Bazel engine regression | [Bazel's upstream remote execution tests](https://github.com/bazelbuild/bazel/blob/master/src/test/shell/bazel/remote/remote_execution_test.sh) provide implementation examples and regression controls. | Reference material; running Bazel's own tests is not an adapter acceptance gate. |

Framework adoption does not replace the existing process contracts or their
negative controls. Pin any introduced testing dependencies. Start with the
repository's pinned Bazel version; select and pin additional versions before
claiming compatibility with them. Passing analysis tests does not demonstrate
that an action executes hermetically or that its cached outputs are portable.

## Starlark validation gates

We use Bazel's Starlark interpreter. These gates validate adapter code and its
use of Bazel APIs against each qualified Bazel version; they do not certify a
new language interpreter. Parsing/linting alone cannot establish action or
repository-rule behavior.

The following gate IDs are local validation identifiers, not roadmap milestones.
Their [milestone owners and exit gates](roadmap.md#validation-ownership-and-remaining-gates)
are scheduled in the [dependency graph](roadmap-graph.md#validation-work-packages).
R01 owns the shared baseline, R02 packages, R03 configurations/SDK extensions,
R04 test rules, and R17 the supported-version matrix. Later feature milestones
extend applicable gates before claiming their new slice.
The baseline and selected package/configuration/test-rule extensions are implemented;
the latter have [native macOS qualification](r02-r04-validation-findings.md).

| Gate | Scope and required assertions | Entry point and current status |
| --- | --- | --- |
| S01: Starlark quality | Pin Buildifier and check formatting plus an explicit lint-warning policy for tracked `.bzl`, BUILD and MODULE files, and materialized generated equivalents. Fail on configured violations; do not silently rewrite files in CI. | Implemented: `python3 scripts/setup-starlark.py`, then `bash scripts/check.sh`; use `python3 scripts/check-starlark.py --workspace PATH` for materialized output. Both the graph generator and explicit-adapter generator are checked by the baseline suites. Exclude downloaded dependencies and Bazel output trees. |
| S02: Helper logic | Use Skylib unit tests for substantial pure Starlark transformations when introduced. Assert meaningful input/output and rejection behavior. | No dedicated suite today. Add only where pure helper logic warrants tests; action registration belongs to S03, repository side effects to S05. |
| S03: Rule analysis | Analyze Shared/App and diamond targets; assert one `MsbuildProject` compile action per node, declared toolchain/runner/input closure, request-file dependency, separate bundle/diagnostic outputs, providers and dependency bundle closure. Check controlled environment and `block-network`/`no-remote` execution requirements, invalid explicit-rule environment keys and missing required providers. | Implemented Skylib analysis suite (`//tests/starlark:core`) for [msbuild.bzl](../bazel/msbuild.bzl) and [graph.bzl](../bazel/graph.bzl). The ten baseline and ten extension analysis targets plus `tests/starlark` aquery checks cover registered actions. Extensions assert package/configuration closure and [graph_test.bzl](../bazel/graph_test.bzl) runfiles, expected tests, data hashes, executable and no-remote policy; invalid names, missing hashes and providers fail. Native probes remain required. Unlike compilation, VSTest requires loopback IPC and intentionally omits `block-network`. |
| S04: Generated-workspace validation | Generate fixtures through preparation, load all intended targets, then inspect configured dependencies and actions using Bazel analysis (`cquery`/`aquery` or analysis tests). Compare observed edges to the independent fixture expectation and exported graph. Exercise supported path/string escaping, stable labels, entry points and deterministic BUILD generation under equivalent manifest ordering; explicitly reject unsupported names. | Partial baseline execution coverage in [test_execute_graph.py](../tests/graph_execution/test_execute_graph.py) and [graph execution findings](graph-execution-findings.md); the baseline `tests/starlark` suite now loads actual prepared diamond targets, checks edges/actions and escaping, and verifies deterministic emission. `tests/starlark_extensions` adds five tests loading real package, selected configuration and test targets; nine published workspaces pass S01. Broader configurations and entry points remain open. Python preparation rejection tests do not substitute for loading generated Starlark. |
| S05: Repository-rule integration | Exercise `local_dotnet_sdk` and `local_native_runtime` in fresh workspaces/output bases. Verify exported tool files, manifest-derived runtime declarations, unsupported manifest schemas, overrides absent from the manifest and controlled valid overrides. Check changed declarations materialize correctly without stale external-repository state. | Partial measured coverage: `python3 -m unittest discover -s tests/sdk_repository -v` checks optional imports and rejects an empty SDK; see [SDK repository findings](sdk-repository-findings.md). [probe_bazel.py](../tools/probe_bazel.py) also exercises runtime overrides. The baseline `tests/starlark/test_repositories.py` now covers runtime schema/override rejection, payload substitution and manifest refresh in reused/fresh output bases. Requires the applicable installed SDK or Nix runtime slice. |

S01–S04 start at Bazel 8.4.2. The baseline has native macOS ARM64 and local Linux ARM64 evidence; record Linux x86-64 separately when
that deferred lane resumes; S05 must also identify the setup or Nix
toolchain and platform. Additional Bazel versions require explicitly pinned runs.
For each implemented gate, add its exact runnable entry point, CI job, qualified
platform/configuration and findings link here before marking it passed.

Analysis assertions should compare semantic properties, not incidental command
formatting. The graph rule's direct labels encode project edges, while its
`GraphBundle` provider carries all reachable dependency bundles. In the diamond,
App depends directly on Left and Right and replays Left, Right and Shared; Shared
has one producer. Assert that closure and exclude unrelated sources and dependency
diagnostics. Do not narrow this to direct bundles without a separately validated
change to the replay contract. Configured identity generation and input discovery
also require exporter/preparation tests; rule analysis alone cannot prove them.

The root `bazel query //:repo_setup` only loads the scaffold. It does not load the
adapter rules through a generated fixture or inspect their registered actions.
Buildifier and query success are therefore insufficient for S03/S04 acceptance.

## Acceptance matrix

“Recorded” below means evidence exists in the linked findings, not that the case
was rerun while writing this document. A result for the explicit two-project
adapter must not be promoted to generated-graph support.

| Contract | Required observation | Existing evidence or planned gate |
| --- | --- | --- |
| Baseline behavior parity | Compare a separate ordinary MSBuild baseline with the adapter build; check application output and compilation markers. | Recorded for the explicit adapter in [Bazel findings](bazel-findings.md) and package-free diamond in [graph execution findings](graph-execution-findings.md). Additional bounded [configured execution](configured-execution-findings.md) and [Serilog adapter](serilog-adapter-findings.md) results are separate evidence. Matching output/markers establishes fixture parity only. Each additional supported scenario must specify its runtime assets, generated outputs, target results or failure comparisons; it is not general MSBuild equivalence. |
| Declared action boundary | Inspect each node's action inputs, outputs, arguments, environment and required dependency bundle closure; unrelated project sources must not leak into consumers. | Existing execution/input checks in [Bazel findings](bazel-findings.md). Add analysis assertions for both rule implementations; generated nodes must use per-node input slices, not the complete graph manifest. |
| Input discovery and graph refresh | Add/remove a globbed source, introduce an optional import, and change a project edge; rerun the supported discovery/preparation flow and verify Bazel sees the new inputs/edges and resulting behavior. | Recorded new-source, optional-import and conditional-edge controls in [graph handoff findings](graph-handoff-findings.md), run via `tests/graph_handoff`. [SDK discovery](input-discovery-findings.md) adds bounded analyzer/import/signing discovery; arbitrary undeclared filesystem probes remain unsupported. Hashing previously declared inputs alone does not cover discovery. |
| Selective invalidation | Cold build executes all nodes; unchanged build executes none; observable source/import/package edits execute the expected dependent actions. | Explicit-adapter [identity](action-identity-findings.md) and [package](package-input-findings.md) results. Generated-graph package-free and managed-package cases are implemented with [R01 findings](graph-cache-findings.md) and [R02 findings](graph-package-cache-findings.md); run `tests/graph_cache` and `tests/graph_cache_full`, respectively. |
| Dependency replay | Consumers use staged dependency artifacts/results under strict isolation without recompiling dependencies. Reject missing artifacts and incompatible identities. Force the consumer to execute when testing replay; a consumer cache hit does not exercise it. | [Replay findings](replay-findings.md), [graph execution findings](graph-execution-findings.md) and forced-consumer [handoff controls](graph-handoff-findings.md). The latter use direct ActionRunner invocations, not transport of modified bundles through Bazel cache. |
| Native sandbox execution | Real compile actions report the native sandbox strategy; undeclared required inputs fail. No fallback to unsandboxed execution counts as a pass. | [Bazel findings](bazel-findings.md) and [runtime integrity findings](native-runtime-integrity-findings.md). Full host/runtime closure remains open. |
| Deterministic staging | Force two fresh executions with separate output bases and empty caches; compare every consumer bundle file's bytes and executable bit. | Recorded macOS evidence in [staging findings](staging-findings.md); a cache hit alone cannot prove determinism. |
| Local cache recovery | Delete build outputs and output base, retain only the allowed inputs and disk cache; prove cache hits, compare recovered bundles and run App. | Explicit-adapter [Bazel findings](bazel-findings.md); generated-graph recovery is recorded in [package-free](graph-cache-findings.md) and [managed-package findings](graph-package-cache-findings.md). |
| Workspace relocation | Use a different workspace path with the producer absent; distinguish replay execution from cache restoration. | [Replay findings](replay-findings.md) and focused Linux [managed-package findings](binary-package-findings.md). Generated-graph cache relocation is recorded in [R01](graph-cache-findings.md) and [R02](graph-package-cache-findings.md), with configured variants in [configured execution findings](configured-execution-findings.md). |
| Invalid input rejection | Missing/corrupt payloads, stale restore/graph metadata and incompatible configuration fail with the specified diagnostic before prohibited compilation or plan publication. | Existing [package](package-input-findings.md) and [managed-package](binary-package-findings.md) controls; generated-graph controls have [package-cache](graph-package-cache-findings.md) and [handoff](graph-handoff-findings.md) evidence. Exact diagnostics and validation boundaries remain case-specific. |
| Independent-worker remote cache | Worker B starts with an independent checkout and empty local caches, retrieves worker A's results from the remote cache, verifies bundles and runs App/tests. Retain client/server cache evidence. | Planned R13 in the [roadmap](roadmap.md); local disk-cache results do not establish this gate. |
| Remote execution | Force cache misses and prove compile actions execute on remote workers with declared inputs and no local fallback. Verify outputs and behavior separately from remote cache hits. | Planned R14 in the [roadmap](roadmap.md); requires its own execution-closure evidence. |

For future analysis tests, assert semantic action properties rather than a full
snapshot of incidental paths or command formatting. Include configured-node
identity, declared toolchain/package inputs, dependency replay closure, output
ownership and the current remote-execution/cache restrictions. Analysis tests
cannot inspect runtime file reads or establish MSBuild output equivalence.

## Running the existing validation

Use a fresh fixture copy; never build inside the checked-in fixture. Install
pinned tools with `bash scripts/setup.sh`, or use `nix develop` and the repository
wrappers. Preparation/restore may need network access. Compile actions must use
the prepared input boundary.

```sh
bash scripts/check.sh
python3 -m unittest discover -s tests/e2e -v
python3 -m unittest discover -s tests/graph -v
bash scripts/dotnet.sh run --project tests/ActionRunner.Tests -c Release
python3 -m unittest discover -s tests/graph_execution -v
```

The scaffold check validates shell/Python syntax, tool pins and tracked Starlark
formatting/lint; it does not run build acceptance. Inside Nix, first acquire
Buildifier with `python3 scripts/setup-starlark.py`. The ordinary e2e command skips the
native-runtime test unless `SPIKE_NATIVE_RUNTIME_TEST=1` is set, including inside
an interactive Nix shell. Run that existing focused mode explicitly:

```sh
nix develop --no-update-lock-file -c env SPIKE_NATIVE_RUNTIME_TEST=1 python3 -m unittest discover -s tests/e2e -p test_bazel_boundary.py -k test_native_runtime_closure -v
```

This enables the runtime payload, loader and JIT controls in the native-runtime
probe. A pass establishes that experiment's slice, not full host/runtime closure.
Record skips separately; an ordinary e2e pass is not a runtime-gate pass.
The setup and Nix workflows exercise e2e validation on Linux; the graph and graph
execution workflows cover their separate suites. A configured CI job is not
proof of a passing run: link the completed run and retained evidence in findings.
Native macOS results do not imply Linux acceptance or cross-platform cache reuse.

Generated-graph cache acceptance now has separate package-free and full managed-
package suites:

```sh
python3 -m unittest discover -s tests/graph_cache -v
python3 -m unittest discover -s tests/graph_cache_full -v
python3 -m unittest discover -s tests/graph_handoff -v
python3 -m unittest discover -s tests/sdk_repository -v
```

The [historical red result](graph-cache-contract.md#first-red-result) predates
implementation; it is not the current suite status. Consult the current
[cache contract](graph-cache-contract.md), [R01 findings](graph-cache-findings.md)
and [R02 findings](graph-package-cache-findings.md) for measured scope.

The additional selected R02–R04 gate is
`python3 -m unittest discover -s tests/starlark_extensions -v`, paired with the
analysis, package, configured and native test commands in
[qualification findings](r02-r04-validation-findings.md). The Starlark CI workflow
now acquires pinned Serilog inputs and enables its native suites; that workflow
configuration has not yet been observed in hosted CI.

These commands are the core rule/build validation paths, not an exhaustive
portfolio run. The native test-rule preparation suite is
`python3 -m unittest discover -s tests/test_action -v`; its native case requires
`SPIKE_SERILOG_SOURCE` and `SPIKE_SERILOG_PACKAGES` (legacy unprefixed names are also accepted). Graph-built Serilog approval acceptance
uses `SPIKE_SERILOG_NATIVE_TESTS=1` and the source/package/tool prerequisites in
[Serilog test findings](serilog-test-acceptance-findings.md). Preserve exact
expected test names/counts, TRX outcomes and standard Bazel outputs; force test
execution with `--nocache_test_results` when verifying recovered build bundles.
A cached test result or zero discovered tests is not actual test execution.

## Recording a validation result

For each new behavioral change, add a findings entry linked from the
[spike plan](spike-plan.md), with:

- Revision, exact command, OS/architecture, toolchain identity and fixture/configuration.
- Actual exit status and executed case/test count; identify failures and blocked prerequisites.
- Retained report and raw log locations, including Bazel execution strategy, executed nodes/cache hits and MSBuild compilation markers where relevant.
- Baseline/output comparisons and bundle hashes plus executable bits for determinism, relocation and recovery cases.
- Negative-case diagnostic and evidence that forbidden work did not run; nonzero exit alone is insufficient.
- Exact test/probe entry point and CI job/run, where applicable; identify the gate ID or acceptance row and supported fixture/configuration.
- Remaining limitations, partial assertions and the specific matrix rows the result establishes. A findings link is not evidence that every assertion in a broader row passed.

Keep fresh execution, unchanged reuse, disk-cache recovery and remote recovery
as separate observations. Do not synthesize reports or treat missing tooling,
network, sandbox support, skipped cases or an unimplemented probe as passes.
