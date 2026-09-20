# Reusing validation within an immutable lifetime

Prepared package hashes now flow into the staged session manifest. The plugin
still verifies all staged content before accepting a build and again at exit.
A copy race therefore rejects instead of silently establishing a new expected
hash. Generated restore/replay files and ordinary sources are hashed normally.

Private sealed entry bundles use a validation scope across identity, composition
and refresh. The scope is verified again before publication/moving ownership.
The parent similarly shares its entry validation across API identity/projection,
then verifies it again. Final exact publication validation remains enabled.
Remote-hit/non-project graph semantics keep the previous validation path.

## Measurement

Three alternating same-path baseline/candidate Orchard pairs, no competing builds,
.NET 10.0.400 on macOS ARM64, package-copy mode, action-local validation enabled.
All six results contain the identical 3,463 bundle files, byte-for-byte.

- Baseline median: 26.702 seconds.
- Candidate median: 24.830 seconds.
- Saving: 1.872 seconds (7.0%).

Parent workspace hashing falls from about 4.2 to 0.32 seconds, but first-read cost
moves into the plugin's mandatory check; its combined hash checks increase from
about 2.3 to 5.1 seconds. The net improvement, not the removed parent timer, is the
meaningful result. Private-bundle reuse saves additional repeated output passes.

## Validation

Owned runner and required workflow tools build with warnings as errors.
ActionRunner.Tests passes, including same-size/timestamp content mutation and
resealed metadata rejection. A live Orchard staged .nupkg mutation of equal size
and timestamp rejects before compilation. Native sandbox acceptance passes dense
producer parity, producer-deleted remote recovery with zero compiles, and a body
edit with one compile and the expected runtime value. Detailed measurements are
in `validation-reuse-evidence.json`; raw evidence is under
`/private/tmp/validation-reuse-measure`, `validation-reuse-mutation2` and
`validation-reuse-native2`. These entry timings exclude Bazel scheduling and
remote transfer; they are not whole-graph cold-build claims.
