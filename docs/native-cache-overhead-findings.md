# Native cache transfer and cold-start overhead

This extends the [sandboxed native-cache experiment](sandboxed-native-cache-findings.md).
It keeps the same owned package-free net10.0 Release graph, macOS ARM64/Nix SDK,
Bazel 8.4.2 and explicit seed-input boundary. Each improvement was measured
separately, with a retained Bazel server and fresh output bases for each matrix.

## Changes

1. **Skip redundant publication.** A successful seed download produces a receipt
   containing its verified blob digest. After a successful build, the broker still
   validates and packs every output bundle. If its exact digest matches a receipt
   from this invocation and endpoint, it skips the PUT. New, changed, missing or
   corrupt bundles still upload. There are no persistent upload receipts or hidden
   action inputs. Remote eviction after a receipt remains an ordinary future miss;
   neither the previous implementation nor this one guarantees remote retention.
2. **Avoid unused language autoloads in the generated workspace.** The probe passes
   `--incompatible_autoload_externally=` because this workspace uses the custom
   .NET rule and filegroups. This avoids automatically fetching unrelated language
   repositories. It does not change a user's Bazel configuration or impose this
   flag on mixed-language repositories. The [Bazel flag documentation](https://bazel.build/versions/8.3.0/reference/command-line-reference#flag--incompatible_autoload_externally)
   describes the autoload mechanism; execution was verified on pinned 8.4.2.
3. **Retain profiling evidence.** Every Bazel call emits a compressed JSON profile;
   report samples include native-cache GET and PUT counts. Profiles contain nested
   and parallel spans, so their aggregate durations must not be added as wall time.

The first change reduces unchanged native-cache PUTs from 100 to zero and body-edit
PUTs from 100 to one. Downloads remain 100 and 99 respectively. This deliberately
keeps current remote-byte verification rather than introducing a persistent local
cache in the same change. Archive validation and packing also still run.

## Measurement protocol

The baseline uses `--repeat-uploads --autoload-languages`; the transfer-only
variant uses `--autoload-languages`; the final variant uses neither flag.
Profiling is enabled for all variants. The first two matrices were run before
adding the autoload switch (equivalent to passing `--autoload-languages` now).
Tool identity changes invalidate the experimental cache normally; each matrix
creates a fresh cache service and producer.

Each matrix pairs a raw cold build and three distinct raw body edits with the
integrated path, checks exact runtime DLL hashes, and executes the application
oracle. Cold values are individual observations; body values are medians of three.
Stable outer-hit values are medians of two. Setup restores and tool compilation
are excluded; SDK snapshot capture is charged to cold. Timings include validation,
staging, Bazel, and successful bundle publication, as in the preceding report.
Loopback measurements cannot establish the benefit on a real remote service.

## Results: 100 projects

| Case | Control | Skip verified uploads | Also disable unused autoloads |
| --- | ---: | ---: | ---: |
| Cold, seconds | 33.393 | 33.677 | 32.874 |
| Paired raw cold, seconds | 25.129 | 25.325 | 25.396 |
| Body-edit median, seconds | 3.310 | 3.289 | 3.302 |
| Paired raw body median, seconds | 3.309 | 3.313 | 3.339 |
| Stable outer-hit median, seconds | 1.083 | 1.075 | 1.075 |
| Native PUTs on body edit | 100 | 1 | 1 |
| Native PUTs on unchanged recovery | 100 | 0 | 0 |

Skipping verified uploads changes body time by only 0.6% on loopback, too little
to claim a meaningful timing gain. The reduction in redundant requests is exact.
Disabling unused autoloads reduces the observed cold time by 0.804 seconds (2.4%)
relative to the preceding stage. These are single cold samples, so this is an
observation rather than a statistically established cold speedup. The final
cold build remains 29.4% slower than its paired raw build. Incremental parity is
preserved, with one compilation and 99 project hits per body edit.

The profile explains the direction of the cold change: aggregate
`download_and_extract` spans fall from 3.698 to 0.354 seconds, and the target-pattern
phase falls from about 1.600 to 0.109 seconds. Download spans overlap and are not
an additive saving. In the final run, the action subprocess takes 26.876 seconds
versus raw MSBuild's 25.396 seconds. About 5.998 seconds of the 32.874-second total
is outside that subprocess: controller/SDK capture, startup, analysis, sandbox
setup and output handling. Optimization should focus there before changing the
compilation algorithm again. Ordinary project-cache GETs and output packing
remain repeated work; a future local content store must preserve validation and
declared seed inputs.

## Validation

Both ten-project extended matrices passed, including API changes, missing/corrupt
remote data, SDK identity changes, empty seeds, outage recovery, failed-build
publication prevention and the existing native sandbox probes. All 18 native-cache
unit tests passed. The new test exercises actual HTTP storage, verifies zero PUTs
for an unchanged downloaded bundle, verifies a changed bundle uploads, and checks
that a corrupt download cannot suppress the repair upload.

The sandbox limitations and package/cross-host exclusions from the preceding
experiment remain unchanged. No CI was dispatched.

## Reproduction

Run inside the pinned Nix environment, using fresh short output paths:

```sh
python3 -m unittest discover -s tests/native_cache -v
python3 tools/probe_portable_cache.py --retained --nodes 100 --repetitions 3 --no-extended --repeat-uploads --autoload-languages --output /private/tmp/cost-control
python3 tools/probe_portable_cache.py --retained --nodes 100 --repetitions 3 --no-extended --autoload-languages --output /private/tmp/cost-transfers
python3 tools/probe_portable_cache.py --retained --nodes 100 --repetitions 3 --no-extended --output /private/tmp/cost-final
```
