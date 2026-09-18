# Moving remaining work into Bazel

## Step 1: structural discovery and source binding

Discovery now receives source membership with empty C# placeholders. Actual
source contents are declared by a separate binding action. Only compile-only
C# inputs qualify; using one as an additional/resource/import input rejects the
split. Existing restrictive XML/import policies remain. Project/import/package
content and file membership still invalidate discovery. The binder resolves
Bazel input-tree symlinks and writes only its own output copies.

All 18 qualification cases and five raw-MSBuild DLL/PDB comparisons passed.
Body edits recovered discovery remotely and compiled one project. Adding a source
invalidated discovery; additional-file roles, undeclared reads, failed tests and
live source mutation rejected publication. The owned code checks passed before
the final input-tree copying adjustment; full final checks are recorded below.

| Workload | Previous fresh body edit | Split discovery | Change |
|---|---:|---:|---:|
| Diamond | 7.911 s | 5.139 s | 35% lower |
| Serilog | 13.123 s | 9.276 s | 29% lower |

These are separate qualification runs, not an interleaved A/B speedup claim.
Tools were already built and restore completed; Serilog includes a forced test.
Source/package payloads are still in preparation outputs at this step.
