# PR #66 review

Review baseline: `6fd5793d084be799587ce6c331f3756b663a5b24`.

## Findings corrected

1. **Package rejection could pass for an unrelated subprocess failure.** The
   probe previously accepted any `CalledProcessError`, including a failed
   GraphExport build. It now captures inherited subprocess stdout/stderr,
   requires the failed command to be GraphExport itself and checks the expected
   input diagnostic. Corrupt restore data must produce `NETSDK1060`; package
   cases require their missing-input or hash-mismatch diagnostic. Each rejection
   log is retained. Regression tests reject unrelated build/exporter failures
   and verify capture of both subprocess output streams.
2. **Calibration could finish with changed tools.** It recorded tool identity
   before warm-up and after measurement without comparing a stable measured
   identity. It now captures identity after warm-up and requires an exact match
   at completion. A regression test simulates late tool mutation and verifies
   that the report remains incomplete. Evidence paths overlapping the controller
   are also rejected before creating files or running warm-up.

## Evidence applicability

The fixes change qualification harnesses and their tests. ActionRunner, Bazel
rules, preparation reuse, the pinned toolchain and the build/test benchmark are
unchanged from the review baseline. The initial 85 native cases and 40 Build/Test
samples remain recorded against their original code hashes. The affected nine
package cases and both paired preparation calibrations are rerun with the
stricter checks. New reports and code hashes are under `reviewValidation` in the
[evidence index](local-mvp-evidence.json); original evidence is preserved.

The declared budget is unchanged. These runs remain calibration, not a #7
performance pass. Final release qualification remains #64.

## Review validation results

All 50 preparation unit tests and repository/Starlark checks passed. All nine
native package/restore cases passed the stricter diagnostic checks. Both
calibration workloads completed five fresh/reuse pairs (20 samples), with
unchanged measured source and tool identities.

| Workload | Fresh median | Reuse median | Reuse/fresh |
| --- | ---: | ---: | ---: |
| small | 2.281s | 3.678s | 1.612 |
| serilog | 2.209s | 3.909s | 1.769 |

The ratio gate still fails. No threshold was changed. The unchanged production
code retains its initial native, Build/Test and .NET validation evidence; the
review does not claim those unaffected suites were rerun. No CI was dispatched.
