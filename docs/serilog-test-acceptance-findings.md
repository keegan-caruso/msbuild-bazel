# Unchanged Serilog approval-test acceptance

The ordinary protocol in `tools/probe_serilog_tests.py` copies the pinned
49b5339ce85385dc52d4d8e8f2b8308becf23506 source archive and acquired package cache,
restores/builds the unchanged Serilog.ApprovalTests Release/net10.0 project, then
invokes `dotnet vstest` directly on its DLL. Test time invokes neither MSBuild nor
restore. TRX parsing requires exactly one executed, non-skipped named Fact,
`ApiApprovalTests.PublicApi_Should_Not_Change_Unintentionally`; zero-test success
cannot pass. DLL bytes are checked unchanged across each test invocation.

The unchanged baseline is distinct from intentional failure controls: changed
approved text, missing approved text, and a deliberately injected runtime
InvalidOperationException. All controls must execute one failed Fact and return
nonzero while retaining TRX and raw logs. DiffEngine is disabled and CI mode is
set to prevent an interactive diff application on failure.

Native Bazel test-action acceptance and producer-free relocation now have the
separate measured evidence below. Ordinary results alone do not establish either
behavior.

On macOS ARM64 SDK 10.0.100, the ordinary opt-in test passed in 5.684 seconds,
covering all four real test invocations. Evidence is retained at
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/serilog-test-ordinary-nd_y_iwp/probe`,
with harness log `/private/tmp/serilog-test-ordinary-suite.log`.

`tools/probe_serilog_test_adapter.py` exercises the native qualification:
real `bazel test`, retained standard test outputs/TRX, exact project build
worksets, test-data-only and runtime exception failures, and producer-free
relocation with forced test execution after build bundle disk-cache recovery.
It also requires missing/changed source/package and missing approval data to
reject preparation without publication. Enable the opt-in suite with
`RULES_MSBUILD_SERILOG_NATIVE_TESTS=1` with the pinned source/package cache and explicit
SDK/Bazel paths.


## Native macOS result

The full native acceptance passed in 76.192 seconds on frozen commit `46da6b0`,
using Nix Python 3.13.9, SDK 10.0.100, and Bazel 8.4.2. The original upstream
project files, target-framework declaration, approval test source, and approved
text were unchanged for the passing baseline and relocated cases. SDK reference
negotiation selected the existing Serilog net10.0 inner build; no framework was
removed from the upstream project.

| Case | Project builds executed | Actual test action | Result |
| --- | --- | --- | --- |
| Cold | Serilog, Serilog.ApprovalTests | Yes | Exactly 1 Fact passed |
| Unchanged | None | No; prior test result cached | Cached passing result |
| Approved-text mutation | None | Yes | Exactly 1 Fact failed with ShouldMatchApprovedException |
| Intentional test exception | Serilog.ApprovalTests only | Yes | Exactly 1 Fact failed with intentional-test-exception |
| Producer-free relocation | None; both bundles recovered from disk | Yes, forced | Exactly 1 Fact passed |

All executed build and test actions used `darwin-sandbox`. The test process
invoked the SDK's `vstest.console.dll` directly, with no build/restore invocation.
Each case verified declared test-data hashes, expected test name/count/outcome,
VSTest exit status, retained TRX and runner report. The two failure cases made
`bazel test` return nonzero while preserving standard test outputs and the exact
expected failure diagnostic. The unchanged case deliberately used Bazel's test
cache; its retained passing TRX is not evidence of another test execution.

Before relocation, the original generated workspace, preparation workspace,
relocated preparation workspace, and Bazel output base were deleted. Both build
actions reported disk-cache hits; `--cache_test_results=no` forced a fresh real
Fact. The recovered test bundle matched every cold file hash and executable bit.
Shouldly resolved the declared approved text through the runner's source path
mapping without the original producer checkout.

Missing/changed test source, missing/changed Shouldly package archive, and
missing approval data each rejected preparation with the expected missing/stale/
hash diagnostic and no published output. Freshly changed approval data changed
only the test action, while freshly changed test source rebuilt only the test
project. No package policy or input integrity check was bypassed for these cases.

Evidence: `/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/serilog-native-tests-jjpvurww/probe`.
The root report includes action records, full bundle inventories, real runner
reports, and rejection diagnostics; per-case evidence retains the actual test
outputs and bundle. Harness log: `/private/tmp/serilog-native-approval-acceptance-1.log`.

This qualifies the unchanged pinned Serilog.ApprovalTests project's single Fact
on macOS, including native test execution and local disk-cache recovery. It does
not qualify the larger Serilog.Tests suite, other test frameworks, Linux, remote
execution, or full host/runtime closure. VSTest requires testhost loopback IPC;
this result does not claim network-isolated test execution.
