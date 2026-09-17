# MSBuild-native explicit-input cache prototype

The opt-in `tools/probe_native_cache.py` experiment uses one MSBuild graph build
and an SDK-native `ProjectCachePluginBase` implementation. It removes per-project
MSBuild startup while retaining per-project cache decisions. The normal Bazel
adapter is unchanged.

## Boundary

This is an owned synthetic, package-free, net10.0 Release experiment on macOS
ARM64 using Nix and SDK 10.0.400. The driver is the supported entry point. It
rejects custom targets, packages, nested control files, symlinks, external project
references and unqualified SDK settings before executing the graph. It does not
provide a filesystem sandbox or qualify arbitrary projects or remote caching.

The key contains exact authored input hashes, normalized generated restore
metadata, source namespace membership, shared project/configuration inputs,
requested targets, global properties, direct dependency reference-assembly hashes,
and tool identity. Tool identity covers the plugin, controller modules, generated
import, environment and a snapshot of the pinned SDK. The SDK snapshot is reused
within the probe process under the immutable Nix-store assumption. Mutable SDKs
and full host closure are not qualified.

Each native request copies verified inputs into a fresh workspace with no compiler
outputs. The plugin validates the evaluated graph and inputs, restores sealed own
artifacts and real SDK target results on hits, and lets MSBuild execute misses.
Misses delete own build outputs before compilation. Input verification runs again
before publication. The driver locks the cache for the complete session.

Compiler dependencies use reference-assembly hashes. Runtime composition uses the
current implementation from every producer, including when the application's
compile result was cached. The first prototype exposed transitive `.Reference`
aliases in SDK runtime metadata. The final version validates those entries,
retains each producer's own metadata and composes the entry runtime from current
producers using the existing `CompileBoundary` implementation. It publishes new
entries only after all projects succeed and runtime composition succeeds.

## Reproduction

Inside the pinned `nix develop` shell, from the repository root:

```sh
python3 -m unittest discover -s tests/native_cache -v
python3 tools/probe_native_cache.py --output /private/tmp/native-cache-10
python3 tools/probe_native_cache.py --nodes 100 --repetitions 5 --no-extended --output /private/tmp/native-cache-100
```

Choose unused, short absolute output paths. The driver records setup, per-request
logs, cache events and a JSON report. Plugin bootstrap and fixture restore are
outside timed builds. Native build timing includes input qualification, staging,
MSBuild, runtime composition and successful scratch cleanup. The initial SDK
snapshot is charged to the native cold build. App execution and DLL comparisons
are correctness checks outside the timer. Raw MSBuild keeps ordinary incremental
build directories; native requests always start without compiler outputs.

## Correctness evidence

The ten-project extended probe checks fresh-workspace recovery, relocation, body
and API edits, source addition/removal, changed props, corrupted payload recovery,
failed-build non-publication and custom-target rejection. An API edit compiles
three projects in both modes; a body edit compiles one. A corrupt root payload is
rejected and rebuilt. A failed root compilation adds no cache entries, and the
next valid request recovers all ten projects from cache.

Every successful sample executes the application and verifies its output. Paired
cold, unchanged and body-edit samples additionally compare every entry runtime
DLL with raw MSBuild byte-for-byte. Unit tests cover qualification and exact source
hashing versus restore path normalization. Owned .NET build/style checks also pass.

## Remaining scope

This proves a scheduling/cache direction, not production readiness. There is no
package, Test, arbitrary target, multi-framework, Windows or Linux qualification.
Only the entry runtime is fully composed; cached library directories do not
recreate every SDK intermediate. Configuration and project-file changes
conservatively invalidate the entire graph. Storage is a simple local directory
cache without eviction or remote service support. The manifest is trusted output
of the owned controller, not an untrusted public API. Local corruption checks do
not establish remote authenticity. No CI was launched for this experiment.

## Measured 100-project fan graph

Cold is one sample; unchanged and body edits are medians of five alternating
paired runs. These are local observations, not statistical or platform qualification.

| Case | Raw MSBuild | Native cache | Raw / native |
| --- | ---: | ---: | ---: |
| Cold build | 26.025s | 28.301s | 0.92× |
| Unchanged / cache recovery | 2.965s | 1.232s | 2.41× |
| Root body edit | 3.391s | 1.713s | 1.98× |

Unchanged native runs recover 100 cache entries into empty build directories.
Each body edit compiles one project and recovers 99. Raw MSBuild also compiles
one project on body edits. DLL equality and application output checks pass
for every measured pair. The ten-project API edit compiles three in both modes.
