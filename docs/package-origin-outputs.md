# Package-origin project outputs

The opt-in `package-origin-outputs` owned-workflow flag replaces duplicate package
files in project bundles with sealed references to declared Bazel package inputs.
It requires `project-actions` and `package-actions`; it defaults to false.
The equivalent compile-rule attribute is `package_origin_outputs`.

## Representation and ownership

Schema 3 preserves the full logical `artifacts.json` index, including each output's
path, size and SHA-256. A sealed `package-origins.json` maps omitted artifact paths
to `package-id/version/relative-path`. Selection uses exact nonempty content hashes
from the already verified package payload, with deterministic selection if several
package files contain identical bytes. Empty artifacts remain physical files.

The transport validator checks the origin-map seal, safe relative paths, logical
membership and exact physical inventory. Consumers resolve origins exclusively
through declared package inputs and verify their size and hash. There is no lookup
in an ambient NuGet cache. Sparse inputs and their package bytes are checked again
before publication, including rejection of a valid but changed origin-map seal.

Compilation expands sparse dependency metadata into a private dense replay view;
artifact links refer to declared bundle/package inputs. Existing replay validation
and MSBuild behavior continue to operate on the dense view. Final runtime composition
resolves package bytes directly from Bazel inputs. The final application remains
self-contained, with the same bytes as the dense implementation.

This first implementation compacts bundles after capture and projection. It reduces
the physical bundle outputs but still pays for their initial capture and copies.
It does not eliminate all package staging during MSBuild execution.

## Large-project measurement

The experiment uses the retained Orchard CMS entry request, with all 201 dependency
results available, the same host SDK 10.0.400, package-copy mode and no shared
compilation. It alternates baseline/candidate/candidate/baseline/baseline/candidate,
uses identical output paths, and excludes Bazel scheduling and remote transfer.
Unchanged dependency bundles retain the exact baseline paths. None of these 201
dependency API bundles contains a nonempty package-origin artifact, so this workload
measures output compaction rather than sparse dependency replay savings.

Each candidate omits 5,374 physical package files totaling 891,389,738 bytes across
the entry and API bundles. Each bundle individually omits 2,687 files and
445,694,869 bytes. The comparison reconstructs and verifies logical contents for
entry, API and runtime outputs, including dense seal identities: 6,932 files per run.

Three alternating matched-path pairs give:

- Dense baseline median: **22.289 s** (22.629, 22.095, 22.289).
- Package-origin median: **22.738 s** (22.738, 22.556, 22.830).
- Added action time: **0.449 s (2.0%)**.

All six runs retain identical logical output. This is a representation improvement,
with a small measured execution cost rather than a demonstrated speedup. An earlier
six-run comparison used cloned paths for unchanged dependency bundles (22.927 s
dense versus 23.023 s sparse); the matched-path result above supersedes it.
Both measurements are retained in [the evidence](package-origin-outputs-evidence.json).

## Native sandbox and cache qualification

`direct_cache_probe.py --acceptance-only --package-origin-outputs` uses a four-project
graph with Newtonsoft.Json and PolySharp. An executable dependency ensures that
both a dependency and the final entry actually produce schema-3 API bundles.
This stays within the supported project XML boundary; it does not add support for
arbitrary `CopyLocalLockFileAssemblies` overrides.

- Dense baseline and sparse producer have identical application hashes and print `11`.
- After deleting the producer, a fresh worker recovers with zero compiles, identical
  application hashes and no package payload files downloaded.
- Editing the executable dependency runs one compile and changes output to `21`.
- Editing the entry runs one compile, consumes the sparse dependency and prints `31`.
- Invalid publication and retry controls pass.
- Unit controls reject missing declared packages, changed package bytes, unexpected
  physical artifacts, unsafe origins and resealed origin-map changes within a lifetime.

Raw native evidence is `/private/tmp/package-origins-native-dependency`.

Owned tool builds pass with warnings as errors. ActionRunner.Tests, 33 preparation
tests and 68 applicable workflow tests pass. One Linux-only sandbox test is skipped
on macOS. The bootstrap test initially picked Darwin's incompatible `sha256sum`;
rerunning it with pinned GNU coreutils on PATH passes. C# formatting, buildifier and
`git diff --check` pass. No CI or Linux qualification was run for this change.

## Decision and remaining cost

Keep this opt-in. Runtime composition currently declares the entry's full package
closure. When it executes after the dependency edit, the fixture materializes both
Newtonsoft.Json (24 files) and PolySharp (13 files); the dense fixture previously
kept PolySharp remote. Full runtime cache hits still avoid downloading these inputs.
Narrowing runtime package declarations is necessary before enabling this by default.

The omitted byte count is a reduction in physical bundle contents, not a measured
network saving. Bazel's content-addressable store already deduplicates identical
bytes. Remote download/materialization behavior and full-graph cold-build effects
need separate measurement. Avoiding package copies during capture/projection is
the next implementation opportunity once the representation is qualified.

## Reproduction

Build the owned tools and ActionRunner.Tests first. With the retained Orchard
request and execroot, use:

```sh
python3 tests/remote_workers/optimization_probe.py \
  --package-origin-outputs --test-helper "$ACTION_RUNNER_TESTS" \
  --request "$ORCHARD_REQUEST" --execroot "$ORCHARD_EXECROOT" \
  --output "$NEW_MEASUREMENT_DIRECTORY" --dotnet "$DOTNET" \
  --baseline "$STEP_TWO_RUNNER" --runner "$PACKAGE_ORIGIN_RUNNER"

python3 tests/remote_workers/direct_cache_probe.py \
  --acceptance-only --package-origin-outputs \
  --output "$NEW_ACCEPTANCE_DIRECTORY" \
  --repositories "$BAZEL_REPOSITORY_CACHE" --cache-binary "$BAZEL_REMOTE"
```

The native probe uses `RULES_MSBUILD_DOTNET_ROOT` and `RULES_MSBUILD_BAZEL`.
