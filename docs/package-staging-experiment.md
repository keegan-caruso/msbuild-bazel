# Package staging experiment — paused

Status: experimental instrumentation and opt-in prototype, not qualified for
production. Paused on 2026-09-19 at the user's request for disk cleanup.

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
The first borrowed-input run was interrupted for the pause. There is no completed
candidate timing, byte-parity result, sandbox qualification, or dedicated
regression coverage yet. Do not enable the option by default on this evidence.

The baseline suggests package copying alone has a modest ceiling on this final
project: about 1.6 seconds, versus 4.4 seconds of initial payload validation.
This does not establish the corresponding full-graph savings. The earlier
completed dependency-staging optimization remains documented in
[compile-staging-performance.md](compile-staging-performance.md).

## Resume

The four-run plan is copy, borrow, borrow, copy at identical output paths, with
all outputs hashed after each invocation. Finish those measurements, test input
mutation and read-only sandbox behavior, and retain the change only if the full
cost improves. Full Orchard hermetic qualification and asynchronous cache-upload
measurement are still outstanding; neither is represented as passing here.

The instrumented baseline and exact hashes were saved under
`/private/tmp/package-staging-evidence`. The current prepared inputs live under
`/private/tmp/orchard-staging-state`; preserve them until measurements resume or
regenerate them using the saved workflow request.
