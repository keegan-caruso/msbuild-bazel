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

Native Bazel test-action acceptance and producer-free relocation are being
qualified separately. Ordinary results alone do not establish either behavior.

On macOS ARM64 SDK 10.0.100, the ordinary opt-in test passed in 5.684 seconds,
covering all four real test invocations. Evidence is retained at
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/serilog-test-ordinary-nd_y_iwp/probe`,
with harness log `/private/tmp/serilog-test-ordinary-suite.log`.

`tools/probe_serilog_test_adapter.py` defines the pending native qualification:
real `bazel test`, retained standard test outputs/TRX, exact project build
worksets, test-data-only and runtime exception failures, and producer-free
relocation with forced test execution after build bundle disk-cache recovery.
It also requires missing/changed source/package and missing approval data to
reject preparation without publication. Enable the opt-in suite with
`SPIKE_SERILOG_NATIVE_TESTS=1`; these assertions are not passing evidence until
run against the integrated test rule and downstream framework implementation.
