# Compilation dependency staging

Project actions now consume sealed Bazel dependency bundles directly and reuse
their validation results within one build session. Actual compiler inputs remain
private copies. Per-project action boundaries and remote-cache identities retain
their existing semantics; the changed tool binaries invalidate previous actions.

## Repeated work removed

Previously, the runner validated each dependency bundle, copied the entire bundle
into private scratch, and normalized that copy. The cache plugin then validated
and copied its artifacts into the build workspace. While computing dependency
identities and composing each dependency's runtime closure, it repeatedly hashed
the same sealed bundles.

The runner now validates the declared bundles and passes their paths to the
plugin. Only the compiler-visible artifacts are copied into the private workspace.
Those destination copies receive the same writable permissions and epoch timestamps
as before, with executable status preserved. Static-web-asset manifests are rebased
in those private copies. There are no writable aliases or hardlinks to dependencies.

The plugin caches validated artifact lists only for its prebuilt dependencies,
within the current build session. Freshly produced bundles continue to use direct
validation. A final full rehash checks all borrowed bundles before plugin
publication; the runner also rechecks its dependencies after output projection and
before returning success. Changes to either payloads or sealed metadata fail the
action. No validation state is shared between actions or workers.

## Isolated Orchard action measurements

The CMS web project consumes 201 dependency bundles and 287 package directories.
Each probe compiled that entry once with the same prepared inputs and exact output
path, deleting its prior private outputs between samples. These are standalone
runner measurements, outside Bazel's native sandbox, with filesystem cache state
retained. They isolate staging changes; they are not whole-workflow timings.

| Implementation | Samples | Median action phase total |
|---|---:|---:|
| Baseline | 3 | 30.559s |
| Session-local dependency validation | 2 | 27.818s |
| Also remove intermediate dependency copies (retained) | 2 | 25.434s |
| Also reuse prepared input hashes (discarded) | 2 | 25.850s |

The retained implementation saves 5.124 seconds (16.8%) on this project. All 6,932
output files were byte-identical in every sample, including API and runtime
projections. Identical paths deliberately avoid the separate Razor path problem;
this does not establish independent-worker reproducibility.

Sample order was baseline, validation, baseline, validation, direct, direct,
hash-reuse, baseline, hash-reuse. The hash-reuse experiment reduced setup time but
did not improve overall time over direct staging, so it was removed. Sample counts
are small and host/filesystem variation remains visible.

## Validation

Regression checks cover dependency mutation with unchanged size/timestamp,
resealed payload or metadata mutation within an existing validation scope, fresh
scope isolation, private writable copies with normalized timestamps and executable
permissions, and rebasing static-web-asset manifests from read-only inputs without
modifying those inputs. Action-runner contract/process tests pass.

Owned-tool builds and formatting pass, as do five code-style tests, 33 preparation
tests, and 69 workflow tests with one Linux-only skip. The first sandbox-restricted
attempt had environment failures from the host checksum command and unavailable
native sandbox access; rerunning with Nix coreutils and native permissions passed.
No CI run.

## Complete Orchard workflow

The fresh-state native macOS ARM64 workflow passed with all 202 project
compilations, 202 bindings, 287 package extractions, and restore/discovery executed.
There were zero action-cache hits and zero cache-transport failures. The workload
uses SDK 10.0.400, Bazel 8.4.2, two jobs, the same Orchard source as the previous
cold run, retained verified NuGet archives/repository downloads, and the existing
loopback cache service. Validation and gated publication are included in timing.

| Measurement | Previous cold run | Candidate |
|---|---:|---:|
| Full workflow | 662.914s | 647.402s |
| Discovery action | 91.815s | 98.225s |
| Compile source/restore staging, aggregate | 106.223s | 107.824s |
| Compile session setup, aggregate | 138.051s | 122.330s |
| MSBuild/plugin work, aggregate | 477.572s | 455.146s |
| Compile cleanup/projection, aggregate | 50.576s | 47.596s |

The observed full-workflow reduction is 15.512 seconds (2.3%). These are single
full runs, so host/filesystem variation remains a material limitation. Aggregate
action times overlap across two concurrent jobs and cannot be added to get wall
time. The unchanged source/package staging phase shows no improvement; this change
primarily saves dependency setup and plugin validation work.

The application returned HTTP 200 and passed the C#, CSS, and Razor marker checks.
Runtime checks were outside the timer. The 3,457-file app has 3,293 byte-identical
files versus the previous cold build; 82 DLLs and 82 PDBs differ, matching the
count/types of the existing Razor path-dependent limitation. This run does not
establish byte-identical independent producers. The identical-path isolated probes
above provide the byte-parity evidence specifically for these staging changes.

## Evidence and remaining work

See [machine-readable measurements](compile-staging-performance-evidence.json).
Standalone requests, hashes, logs and timings are retained under
`/private/tmp/compile-staging-probe`. Full workflow requests, reports, runtime
checks and output-difference lists are under `/private/tmp/orchard-staging-evidence`.
The benchmark's Bazel server and application were stopped after validation.

Reproduce the owned workflow using a fresh state/output location in its saved
request, with the pinned tools and declared source/package inputs available:

```sh
dotnet tools/Preparation/bin/Release/net10.0/Preparation.dll owned-workflow \
  --request /private/tmp/orchard-staging-evidence/request.json
```

NuGet payloads still receive private per-action copies and input verification.
This change does not introduce a shared writable package cache or weaken the
source/input publication barrier. Reducing package-copy costs further is separate
from the dependency-copy and repeated-validation savings measured here.
