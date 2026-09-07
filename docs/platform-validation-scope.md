# Active platform validation scope

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
Automatic push validation for `codex/ready-tracks` is paused in the setup, Nix and
graph-execution workflows. Main and pull-request checks remain enabled; manual
setup/Nix/graph-execution runs remain available when Linux validation resumes.
No new Linux, cross-platform cache, remote-cache or full host-closure claim is made.
