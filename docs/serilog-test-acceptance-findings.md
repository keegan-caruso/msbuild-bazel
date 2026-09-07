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
