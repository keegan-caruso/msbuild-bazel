# Package staging experiment

Status: the prototype measurements below are retained as historical evidence.
[Bazel integration and full-graph qualification](read-only-package-actions.md)
now pass, and the qualified owned project/package workflow enables borrowing
by default with an explicit copy-mode override.

## Completed baseline

The prepared Orchard CMS entry action consumes 201 dependency bundles and 287
package directories. One new instrumented baseline completed successfully:

| Measurement | Copy baseline |
| --- | ---: |
| Whole runner invocation | 28.736 s |
| Source and restore phase | 6.249 s |
| Prepared payload validation within that phase | 4.353 s |
| Package copying within that phase | 1.623 s |
| Package files | 12,017 |
| Logical package bytes | 2,146,600,383 |
| Session setup | 5.243 s |
| MSBuild/plugin work | 13.528 s |
| Cleanup/projection | 3.463 s |
| Output files hashed | 6,932 |

Validation and package-copy times are components of the source/restore phase,
not additional whole-action costs. This is one sample outside Bazel's sandbox,
with prepared inputs and retained filesystem caches. It is not a new complete
Orchard workflow measurement.

## Prototype and limits

`borrowPackageInputs` defaults to false. The opt-in path creates individual
symlinks at the same private logical NuGet paths, pointing to declared read-only
package files, instead of copying their bytes. Writable files are rejected.
Prepared payload hashes are checked before staging and borrowed files are
rehashed before successful runner return. Existing plugin input checks remain.
Source and restore metadata still use private files.

The owned NativeProjectCache project builds with zero warnings and errors.
At the earlier checkpoint, the first borrowed-input run was interrupted for the
pause. Candidate timings and regression coverage were still outstanding. The
completed resumed measurements and remaining limits are recorded below.

The baseline suggests package copying alone has a modest ceiling on this final
project: about 1.6 seconds, versus 4.4 seconds of initial payload validation.
This does not establish the corresponding full-graph savings. The earlier
completed dependency-staging optimization remains documented in
[compile-staging-performance.md](compile-staging-performance.md).

## Original resume plan

The four-run plan is copy, borrow, borrow, copy at identical output paths, with
all outputs hashed after each invocation. Finish those measurements, test input
mutation and read-only sandbox behavior, and retain the change only if the full
cost improves. Full Orchard hermetic qualification and asynchronous cache-upload
measurement are still outstanding; neither is represented as passing here.

The instrumented baseline and exact hashes were saved under
`/private/tmp/package-staging-evidence`. The current prepared inputs live under
`/private/tmp/orchard-staging-state`; preserve them until measurements resume or
regenerate them using the saved workflow request.

## Resumed results (2026-09-19)

Two copy/borrow/borrow/copy sequences completed at fixed output paths. The
first copy invocation had extra filesystem-cache overhead, so the second warm
sequence is the primary comparison:

| Mode | Samples (seconds) | Median |
| --- | --- | ---: |
| Copy | 24.379, 24.623 | 24.501 |
| Borrow read-only files | 22.230, 22.190 | 22.210 |

The reduction is **2.291 seconds (9.35%)** for the CMS entry action, not a
measured full-graph speedup. Package staging falls from about 1.60 to 0.67 s
and session setup from about 4.50 to 1.82 s. Final validation/projection/cleanup
rises from about 3.46 to 4.58 s because borrowed inputs are rehashed. Initial
payload validation and existing plugin checks remain enabled.

All eight measured runs and one subsequent sandbox run produced identical
hashes for 6,932 files. The sandbox run used `sandbox-exec` to deny network
access and writes beneath the declared-input execroot. It passed after the
final metadata-write safeguard was added: restore metadata replaces a symlink
with a private file before writing, so it cannot chmod or overwrite a borrowed
package. This is a focused macOS sandbox check, not a full Bazel graph run.

Regression tests verify writable-input rejection, unchanged-input acceptance,
post-link mutation rejection, and cleanup preserving the original package.
NativeProjectCache and ActionRunner.Tests build with warnings as errors; action
runner contract/process tests and focused formatting checks pass.

At this prototype checkpoint the option remained false by default and was not
emitted by production Starlark. The subsequent integration and acceptance,
including actual Bazel sandbox links and fresh remote recovery, are documented
in [read-only package actions](read-only-package-actions.md).

Evidence and all phase timings: `package-staging-resumed-evidence.json`. Raw
reports, hashes and logs remain in `/private/tmp/package-staging-resumed`,
`/private/tmp/package-staging-warm`, and `/private/tmp/package-staging-sandbox`.
The initial paused sections above describe the earlier checkpoint only.
