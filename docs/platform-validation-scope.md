# Active platform validation scope

On 2026-09-07 the user requested local Linux validation through the
[Apple container workflow](apple-container-runbook.md). The Starlark baseline
now uses a native Linux ARM64 guest alongside the recorded native macOS lane.
This supersedes the Linux deferral below only for that selected local ARM64
validation. Linux x86-64 CI, Nix runtime closure and cross-platform cache reuse
remain separately qualified work. Results are recorded in the
[Starlark findings](starlark-core-findings.md).

## Earlier decision and evidence

At the user's request on 2026-09-06, defer further Linux validation and
continue implementation and acceptance on native macOS ARM64. This changes
milestone scheduling, not the platforms established by previous evidence.

R01 retains its measured native Linux and macOS results at `c384671`.
The R02 managed-package slice passes the full 13-test cache suite and 14
PrivateAssets/restore-state tests on macOS at `6563e3c`; see the
[correctness review](correctness-review-findings.md) and
[consumer restore findings](consumer-restore-findings.md).
The selected R03 net10.0 inner build and direct-edge Flavor variants also have
native macOS mutation and relocation evidence in
[configured execution findings](configured-execution-findings.md).
These bounded slices satisfy the active macOS prerequisites for R04.
Unselected outer builds, general configured transitive references and broader
entry-point semantics remain outside that acceptance.

R04 now advances the pinned Serilog library's package generator/analyzer,
signing, resource and shared-import inputs, followed by native adapter/cache
acceptance. The [ordinary input oracle](serilog-inputs-findings.md) is a baseline;
it does not itself establish adapter support or full Serilog test-project support.

Linux jobs for newer changes previously failed before startup because of account
billing/spending limits. Those attempts are not test failures or passing evidence.
All repository CI workflows now use only `workflow_dispatch`: pushes and pull
requests do not launch GitHub CI. Dispatch runs only when explicitly requested
by the user. The one-time round on `9c549f3` dispatched setup, Nix, graph-export and
graph-execution against `main`; GitHub reported failure before validation, with
setup confirming the billing/spending-limit block. The [local consolidation](ci-scope.md)
replaces the three overlapping non-Nix workflows with one quick/full entry point.
The consolidated workflow has not been dispatched.
That decision did not establish new Linux, cross-platform cache, remote-cache or
full host-closure evidence. The later Linux ARM64 results above are separately scoped.
