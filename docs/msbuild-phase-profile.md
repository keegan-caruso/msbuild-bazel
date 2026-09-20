# Orchard entry: where MSBuild adapter time goes

This experiment profiles a single Orchard CMS entry compilation after its 201
project dependencies are available, with package-copy mode and action-local
publication validation enabled. It uses the pinned .NET 10.0.400 SDK on
macOS ARM64. It does not measure a cold whole-graph build or remote transfer.
`msbuild_phase_probe.py` runs one uninstrumented and two instrumented actions at
the same output path, with identical source/package/dependency inputs and
producing-action publication checks. Every run must produce identical entry
bundle files. `profileMsbuild` is an opt-in diagnostic runner request field;
normal workflow generation does not enable it. Binary logs omit imported source
contents. Diagnostics remain outside the bundle identity.

Timers are wall-clock measurements. Plugin child phases overlap their parent;
MSBuild task/target times also nest. Do not add parent and child values together.
The plugin uses a separate assembly load context, so its timing file is separate
from the entry driver's timing file. The broad historical `cleanup` bucket has
been split into validation, projection and actual deletion.

## Observations

Preliminary repeated runs isolate approximately 13.4 seconds in the MSBuild child
process. Entry evaluation takes about 0.16 seconds. Plugin begin, project-finished
capture and build-end processing together account for about 10.6 seconds. The
Csc task takes about 1.1 seconds, Copy tasks about 0.5 seconds, and reference
resolution about 0.1 seconds. The expensive child process is predominantly our
plugin work; it is not predominantly project evaluation or compiler execution.

Outside MSBuild, initial workspace hashing takes about 4.2 seconds, dependency
bundle verification about 0.3 seconds, and writing SDK-less replay project files
about 0.03 seconds. Source/package staging takes about 4.2 seconds after warmup,
including roughly 2.3 seconds of prepared-input validation and 1.6 seconds of
package copying. API output projection is about 1.5 seconds and scratch deletion
about 1.2 seconds. These are phases of an isolated action, not all of Bazel's
end-to-end overhead.

The 202 preserved project plans declare 279,531 package-file appearances, with
57,383,869,534 cumulative bytes. There are only 12,017 unique package files,
2,146,600,383 bytes. This counts repeated declarations, not physical disk IO:
filesystem page caching and copy-on-write can reduce actual traffic. It explains
why complete package validation/staging per project scales poorly even without
remote-cache misses on restore/extraction actions.

The entry restores 11,799 dependency artifacts. Its dependency-composition loop
then selects 10,041 additional runtime-file copies into dependency output trees.
This count follows the current closure and selected-output membership algorithm;
it is not a syscall trace. Those writes preserve the current contract today.
Removing them requires proving which replay consumers require those paths.

## Microsoft MSBuildCache comparison

Source examined at commit `54bcfb23a927bead6622eee0cd3f109ae66c9931`, verified
against upstream main during this experiment:

- [DirectoryFileHasher](https://github.com/microsoft/MSBuildCache/blob/54bcfb23a927bead6622eee0cd3f109ae66c9931/src/Common/Hashing/DirectoryFileHasher.cs)
  memoizes a lazy hash task by absolute path. A NuGet input is hashed once per
  hasher instance, even when requested by multiple projects. Our actions instead
  revalidate and reconstruct separate workspaces. Sharing an unchecked path-only
  cache across mutable workspaces would not preserve our mutation guarantees.
- [MSBuildCachePluginBase](https://github.com/microsoft/MSBuildCache/blob/54bcfb23a927bead6622eee0cd3f109ae66c9931/src/Common/MSBuildCachePluginBase.cs)
  tracks observed package reads, matches their hashes against outputs, and records
  package-origin outputs separately. The matching is content-based, not a filename
  guess. This is a useful model for avoiding duplicated package payloads in API
  and runtime bundles while retaining explicit NuGet inputs.
- [CacheClient](https://github.com/microsoft/MSBuildCache/blob/54bcfb23a927bead6622eee0cd3f109ae66c9931/src/Common/Caching/CacheClient.cs)
  deduplicates package placement by destination, uses copy-on-write when supported,
  and waits for dependency materialization before the dependent requires it.
  Output capture remains synchronous before asynchronous publication, because
  later work could overwrite outputs. Independent Bazel actions must finish their
  own declared outputs and validation before successful completion.
- [OutputHasher](https://github.com/microsoft/MSBuildCache/blob/54bcfb23a927bead6622eee0cd3f109ae66c9931/src/Common/Hashing/OutputHasher.cs)
  uses a bounded number of worker tasks to hash outputs. Parallelizing every
  per-project hash loop independently risks oversubscribing Bazel's concurrency;
  first eliminate redundant passes and then measure bounded parallelism.
- [FingerprintFactory](https://github.com/microsoft/MSBuildCache/blob/54bcfb23a927bead6622eee0cd3f109ae66c9931/src/Common/Fingerprinting/FingerprintFactory.cs)
  handles file reads, existence probes and directory enumeration observations
  (probe/enumeration behavior is controlled by a setting). Observed-content-only
  traces are insufficient for pruning our declared inputs.

The applicable direction is to give Bazel ownership of reusable, sealed package
and dependency artifacts, with one well-defined validation boundary and explicit
mutable-output checks. Microsoft runs many project requests in one MSBuild
session; our independent action processes do not inherit its in-memory hash cache.
A persistent worker or prevalidated immutable package tree would need an explicit
lifetime and invalidation contract before reusing this approach across actions.

## Raw MSBuild comparator

`raw_entry_profile.py` restores/builds the same Orchard source and local package
feed once, then deletes only the CMS entry's bin and obj/Release before each of
three BuildProjectReferences=false builds. SDK, host, configuration and disabled
shared compilation match the adapter experiment. Real SDK dependency projects
and their existing outputs remain in the raw build; the adapter uses sealed API
replay and performs extra output verification/projection. This intentionally
measures the cost of the supported entry-build workflow, not identical filesystem
operations. Restore/bootstrap is excluded from entry timings. Neither mode is a
machine-cold test. No competing build benchmarks run during timed entry builds.

## Detailed plugin breakdown

Two final instrumented runs take 26.600 and 26.623 seconds and preserve all 3,463
entry-bundle files byte-for-byte. Their first control run took 29.261 seconds;
initial staging/validation was colder. Earlier warmed uninstrumented control was
26.255 seconds. Treat these as repeated phase attribution, not a claim that
instrumentation accelerates execution.

| Phase | Run 1 | Run 2 |
| --- | ---: | ---: |
| Parent source/restore staging | 4.429 s | 4.509 s |
| Parent workspace hashing | 4.200 s | 4.213 s |
| MSBuild child total | 13.552 s | 13.481 s |
| Plugin begin (inside child) | 5.531 s | 5.503 s |
| Dependency artifact restoration (inside begin) | 1.698 s | 1.705 s |
| Dependency runtime composition (inside begin) | 1.965 s | 1.925 s |
| Plugin output capture (inside child) | 1.808 s | 1.800 s |
| Plugin end (inside child) | 3.339 s | 3.342 s |
| Workspace content checks (two calls across begin/end) | 2.268 s | 2.266 s |
| Workspace namespace checks (two calls across begin/end) | 0.325 s | 0.321 s |
| Build-end bundle refresh (inside end) | 1.393 s | 1.399 s |
| Parent API projection | 1.459 s | 1.465 s |
| Parent publication validation | 0.492 s | 0.501 s |
| Parent scratch deletion | 1.208 s | 1.215 s |

The entry bundle contains 3,460 artifacts totaling 447,488,436 bytes, plus three
metadata files. `Seal` hashes and normalizes that tree. `Identity`, `Compose`,
`RefreshBundle`, parent entry validation and API projection may validate the same
sealed entry again. Dependency `ValidationScope` already memoizes reads within
one scope, but the parent and plugin have different scopes, and freshly produced
entry bundles are not covered by the dependency-only memoization. This is a
specific repeated-work opportunity; hashes must not be reused across mutations.

A preliminary raw comparison (implicit net10.0 selection and the earlier fixture marker) took 10.862, 10.182
and 9.858 seconds. The middle run reports 404 project evaluations totaling 5.417
seconds and one Csc invocation taking 1.063 seconds. MSBuild task totals include
nested dependency requests and exceed wall time; they must not be summed. The
adapter's SDK-less dependency evaluations individually round to zero milliseconds
in the console summary, and its entry evaluation is measured separately at about
0.16 seconds. This confirms the replay strategy already avoids substantial SDK
evaluation work. The remaining gap is adapter work around that useful saving.

## Next changes, in measured order

1. **One validation scope per immutable artifact lifetime.** Carry verified hashes
   through staging/session construction; validate sealed entry output once per
   mutation epoch and reuse its parsed index for identity/projection/selection.
   Retain exit checks for mutable inputs and exact publication validation. Use
   corruption and concurrent-mutation controls to prove equivalence.
2. **One placement plan for replay outputs.** Resolve producer ownership and copy
   destinations once, then materialize only the filesystem contract required by
   the consumer. Target the 11,799 restores plus 10,041 composition copies. First
   prove which dependency-local runtime paths replay targets actually access;
   do not delete them solely because the compiler uses reference assemblies.
3. **Package provenance and immutable Bazel-owned package trees.** Follow the
   reference implementation's content-matched package-origin outputs. Preserve
   declared package dependencies and reconstruct output paths once; avoid
   transporting and rehashing copied package bytes in every API bundle. A cached
   package extraction action alone does not eliminate per-consumer copying/hashing.

These are opportunities, not additive speedup promises. Some phases overlap or
move work to another boundary. Each change needs the same-path output comparison,
producer-unavailable remote recovery, mutation rejection and uncontended timings.

Final raw comparison verifies all 674 supplied adapter source/configuration inputs
byte-for-byte, including the exact entry Program.cs benchmark marker, and selects
TargetFramework=net10.0 explicitly. It takes 10.749, 10.154 and 9.744 seconds
(median **10.154 s**). Final instrumented adapter median
**26.611 s**, or **2.62x** raw,
for this clean-entry scenario. Earlier raw runs are diagnostic history and are
not used in that ratio. This is not a whole-graph or remote-hit timing. Detailed
machine-readable evidence is in `msbuild-phase-profile-evidence.json`.

Validation: owned runner build with warnings as errors and formatting verification
passed. Three final adapter runs produced identical 3,463-file entry bundles; each
raw entry run performed exactly one compile. Python harness syntax checks passed.
No CI was run.
