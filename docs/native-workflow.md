# Opt-in native-cache Build/Test workflow

`tools/native_workflow.py` prepares the qualified Release/net10.0 input graph,
generates `//:build` and optionally `//:test`, runs Bazel, and publishes verified
project bundles to owned local state only after success. The existing graph
adapter remains the default interface; this command explicitly selects the native
backend. The measured platform is macOS ARM64 with the pinned Nix SDK.

## Use

Restore the chosen entry normally with packages under the source checkout's
`.nuget/packages`. Prebuild tools once with `--bootstrap` on the first invocation.
Keep source, controller checkout, owned state and per-invocation report output
paths disjoint, and use short paths on macOS. Run inside `nix develop`.

For the pinned Serilog approval entry, declare test data and expected test names:

```json
{
  "data": [
    "test/Serilog.ApprovalTests/ApiApprovalTests.cs",
    "test/Serilog.ApprovalTests/Serilog.approved.txt"
  ],
  "expectedTests": ["ApiApprovalTests.PublicApi_Should_Not_Change_Unintentionally"]
}
```

Save that declaration as `/private/tmp/tests.json`, then run:

```sh
python3 tools/native_workflow.py --bootstrap \
  --workspace /private/tmp/serilog --state /private/tmp/native-state \
  --entry test/Serilog.ApprovalTests/Serilog.ApprovalTests.csproj \
  --tests /private/tmp/tests.json --operation test --force-tests \
  --output /private/tmp/native-run1
```

Repeat without `--bootstrap` and with a new `--output`. `--operation build`
selects `//:build`; `--operation test` selects `//:test`. `--force-tests` asks Bazel
to execute VSTest even when its test-result cache could satisfy the request.
Without it, normal Bazel test-result caching applies. The stable generated
workspace is `<state>/g`. Reports record phase timings, actual build/test action
counts, compiler invocations, runtime hashes, and VSTest results. Bazel test logs,
TRX and the standard test XML are retained alongside the report.

The native test rule consumes a separate sealed current runtime bundle, checks its selected input
and toolchain identity, verifies artifact hashes, and stages declared test data.
It invokes VSTest directly and never builds or restores during test execution.
Test data participates in Bazel test identity separately from compilation inputs.

## Scope

This extends the [qualified Serilog slice](native-cache-serilog.md). The
[API/runtime boundary](native-api-runtime.md) separates ordinary project
compilation reuse from current runtime composition. The existing package boundary
and native sandbox limitations remain. Tests run locally; no remote execution or cross-host
cache claim is added. This command currently manages a local project cache.
The separately qualified HTTP broker remains available to experiment harnesses.
Code coverage remains outside the qualified slice.

## Original integration validation

The five-case real workflow probe passed: cold compilation of two projects,
zero-compilation recovery with actual VSTest execution, a golden-data mismatch
that failed the test without publishing cache state, restored golden data with no
compilation, and a library implementation edit rebuilding both projects. Every
case executed exactly one test, with none skipped. Cold/recovered runtime hashes
matched. Reproduce with `tools/probe_native_workflow.py --source <pinned-checkout>
--packages <acquired-packages> --output <new-short-path>`.

The existing graph test-rule probe also passed its pass, mismatch, missing-data
and zero-test controls after extending the shared runner. Owned .NET formatting,
warnings and style-policy checks passed; the new Starlark passes pinned Buildifier.

## Preparation reuse

Add `--reuse` to retain native plans through the existing leased preparation
cache. An unchanged invocation skips GraphExport, evaluated materialization and
package restaging. It still seals and hashes mutable inputs, verifies cached
payloads, stages changed consumer inputs, and checks the lease and borrowed
payload again after Bazel finishes. Project-cache publication occurs only after that final check. Test data
is copied from the leased source snapshot, so tests and compilation share the
same captured view. Test-result caching remains a separate Bazel decision.

The native plan policy is part of the preparation request, including its complete
toolchain digest. Cached native plans and the original graph-adapter plans cannot
alias. Corrupt or incomplete generations fall back to fresh qualified preparation.
The default existing graph adapter keeps its original interface and behavior.

The approval-test discovery extension admits only the package versions already
archive-pinned in `pilot-package-policy.json`. `discovery-test-packages.json`
additionally pins the exact reviewed imports: test SDK program inclusion, xUnit
runtime/adapter items, EmptyFiles content, Shouldly path-map targets and coverage
metadata. Evaluation does not execute the Shouldly inline task; VSTest receives
its source map explicitly. Package payload verification precedes trusting imports.
The SDK import list adds eight fixed files observed during framework negotiation;
this does not enable execution of additional target frameworks or Windows builds.
Authored XML gains only `DeterministicSourcePaths=false`, the generated xUnit
package-path property, and Serilog's exact conditional runtime option.

`--trust-system-nix-store` and `--incremental-sources` explicitly select the existing
protected-store and C# content-refresh policies. Protected-store reuse is confined
to a retained Python process and assumes the integrity of root-owned Nix paths;
a one-shot CLI starts with an empty store-verification cache. Mutable source and
package content is always checked. These options do not change the default.

The reuse probe adds corruption recovery, source namespace invalidation,
package-payload tampering and missing-data rejection. The preparation unit suite
covers candidate integrity, atomic publication, overlapping paths, accepted-lease
changes and no retry of failed consumer commands, plus the new exact policy gates.

The final eleven-case reuse probe passed, including a successful actual Bazel test
followed by an injected mutation of the leased source view: the lease rejected it
and the project-cache publication pointer stayed unchanged. Unchanged cases
reported `reused=true`, `discoveryExecuted=false`, and
`materializationExecuted=false`. All 71 preparation identity/lease/policy unit
tests passed. Earlier runs correctly fell back while the test-package, SDK-import
and exact Serilog runtime-option eligibility additions were incomplete; fallback
reasons are now preserved in workflow reports.

## Complete-workflow timing

The [measurement protocol and results](native-workflow-performance.md) compare the
one-shot CLI and optional retained-controller profile against raw MSBuild/VSTest.
They include preparation and lease checks, actual tests and cache publication.
Fresh preparation, qualified fallback, and native execution use the same disabled
workload-resolver policy for this net10.0 slice, preventing mode-switch false
misses caused by differing SDK imports. The runner reports this as
`evaluated-net10-release-env-v1`; the package-free policy is unchanged.

The [overhead follow-up](native-workflow-optimization.md) retains generated inputs
by content and lets native staging read prepared generations under the existing
lease, with payload verification before use and at consumption exit.

With guarded incremental sources, native plans retain verified package payloads
and update only the admitted C# contents and their project identities. SDK/tool
snapshots are shared within a single command and freshly checked before publishing
project bundles. This adds no persistent mutable-file trust. The explicit
protected-Nix-store option retains its separately documented trust assumptions.
