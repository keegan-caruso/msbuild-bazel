# Evaluated compilation reuse and current runtime composition

This follows the [changed fresh-consumer baseline](native-changed-remote.md).
The evaluated native workflow separates ordinary project compilation identities
from implementation bytes under the versioned `evaluated-api-runtime-v2` policy.
Old evaluated plans and cache keys do not alias.

## Cache boundary

The dependency contract includes reference assemblies, output membership,
canonical replay target metadata, SDK runtime/dependency metadata, package assets,
and transitive dependency contracts. Only DLL/PDB/XML bytes belonging to known
projects in the dependency closure are omitted. Own source, imports, packages,
restore inputs, configuration and controller/toolchain identity still participate
in each project's build key. Runtime metadata and package changes can therefore
conservatively rebuild consumers even when reference bytes are equal.

JSON object properties are sorted before hashing replay metadata; array order is
preserved. MSBuild dictionary enumeration order must not create cache misses.
Missing references, corrupt sealed artifacts, duplicate project assembly names
and colliding package/project runtime names fail validation. Fresh compilations
also verify that each selected copy-local project file equals its producer's
file; consumer output overrides are rejected before cache publication. Analyzer, build-order
and embedded-interop project references retain whole-artifact dependency keys for
the graph. Declared content copies to project DLL/PDB/XML filenames also use
whole-artifact keys, including TargetPath/Link aliases, so coincidentally equal
bytes cannot establish ownership. This is not a new qualification of those
reference roles or custom output behavior.

On a compilation hit, the plugin restores the cached project and replaces its
selected copy-local project files with current producers' DLL/PDB/XML bytes.
It repeats composition for the entry after every project succeeds, preserving
SDK output membership and NuGet metadata. Every producer is verified before
composition writes files.

Compilation bundles stay immutable and may contain historical copied runtime
implementations. The runner publishes a **separate sealed current runtime** at
`build.bundle/runtime/<entry-key>` and exports its executable files under `app`.
Native tests consume that runtime seal, not the compilation-cache bundle. Cache
publication still requires successful build/test and final input/lease checks.

## Correctness protocol

The changed-consumer probes require exactly one compilation for a leaf body edit
or a shared-root body edit. They delete producer sources, preparation state,
local compilation outputs and Bazel state before creating fresh consumers. Only
an immutable HTTP catalog and sealed blobs survive. Runtime hashes must equal
raw MSBuild, the executable must report the changed value, and all native/raw
reference assemblies must match the producer.

The pinned Serilog controls distinguish an existing-method body change from API
changes and package/generator changes. Adding a private method before an async
method changes its generated state-machine name in reference metadata; that case
correctly invalidates the dependent project. It is not used as evidence of
unchanged-reference body reuse. The native workflow also checks that VSTest's
runtime hashes equal the current exported runtime after body-edit recovery.

## Reproduce

Run sequentially in the pinned native macOS ARM64 Nix shell. Restore/package and
SDK acquisition are prerequisites and excluded from both timing paths.

```sh
bash scripts/check-dotnet.sh
dotnet tests/ActionRunner.Tests/bin/Release/net10.0/ActionRunner.Tests.dll
python3 tools/probe_native_serilog.py --source <pinned-serilog> \
  --packages <acquired-packages> --output <new-short-path>
python3 tools/probe_native_workflow.py --source <pinned-serilog> \
  --packages <acquired-packages> --output <new-short-path> \
  --reuse --incremental-sources
python3 tests/preparation_reuse/measure_changed_remote.py \
  --output <new-short-path> --count 100 --repetitions 3 --delay-ms 10
```

The remote measurement includes fresh identity checks, preparation, HTTP download
and verification, staging, Bazel startup/build, runtime composition, final checks
and remote publication. It uses loopback HTTP with 10 ms delay per request on one
host. This is project-bundle CAS reuse inside a native Bazel graph action, not a
standard Bazel ActionResult cache, WAN measurement or independent remote worker.

## Results

Correctness acceptance passes on native macOS ARM64 with Nix SDK 10.0.400 and
Bazel 8.4.2:

- 21 Serilog package/cache controls, including unchanged-reference body reuse,
  private-member and public-API invalidation, a real PolySharp version change,
  relocated HTTP recovery, corruption/missing blobs, actual VSTest execution,
  raw runtime-byte equality and failed-build non-publication.
- 12 native workflow controls, including body-edit recovery with zero compilation,
  VSTest/current-runtime hash equality, source namespace invalidation, corrupt
  preparation repair, package/data rejection and unchanged publication after an
  accepted-lease mutation.
- 84 preparation and 23 native-cache Python tests; ActionRunner contract/process
  tests including the new boundary tests; owned .NET builds, formatting and all
  five style-enforcement controls; environment and 12-file Starlark checks.

The package run includes fresh-output ownership validation. The subsequent
declared-copy alias fallback is covered by boundary unit tests and the final
12-control native workflow run. It preserves the unchanged-reference Serilog
body hit. General custom-output and analyzer-role qualification remains separate.

The original private-method “body” probe correctly rebuilt both projects because
the reference assembly changed. A preliminary small-graph run exposed unordered
JSON metadata hashing; canonicalization fixed it. Preliminary timing runs were
stopped to complete ownership guards and are excluded from the final medians.

| Edit | Previous native | New native | Raw clean | Compiled | Cache hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| leaf | 22.156 s | 21.976 s | 26.184 s | 1 | 99 |
| shared | 47.061 s | 22.136 s | 25.974 s | 1 | 99 |

These are medians of three fresh consumers per edit. All six cases pass the
exact project miss/hit sets, all 100 producer/native/raw reference hashes,
complete runtime-byte equality and changed executable-result checks.

The shared-root body edit is **2.13 times faster** than the
earlier native baseline (53.0% less elapsed time), and
**14.8% faster** than the paired clean raw build. Its compilation
count falls from 100 to 1. The leaf case falls from two compilations to one;
its end-to-end change versus the earlier baseline is
0.8%, too small in this three-run sample to claim a meaningful speed gain.

Fresh preparation remains the main cost: median
**12.130 s** for leaf edits and **12.226 s** for shared edits.
The Bazel phase, including server startup and native execution, takes
7.349 s and 7.407 s respectively.
Reusable discovery/preparation for fresh consumers is the next bottleneck.

| Edit | Download bytes | Upload bytes | Previous upload bytes |
| --- | ---: | ---: | ---: |
| leaf | 5,699,920 | 93,886 | 901,417 |
| shared | 5,748,076 | 45,740 | 5,759,580 |

Each final consumer makes 102 HTTP requests: the catalog and 99 reusable bundles
are downloaded; the changed project bundle and new catalog are uploaded. The
99 compilation hits are distinct from the 100 successful transport reads.

Evidence: final timings `/private/tmp/napix/report.json`, real-package controls
`/private/tmp/napisf/report.json`, final workflow `/private/tmp/napiwx/report.json`.
The earlier baseline is `/private/tmp/nor/report.json`. No GitHub CI ran.
