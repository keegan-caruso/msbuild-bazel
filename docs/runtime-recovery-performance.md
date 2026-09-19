# Canonical runtime outputs, recovery and no-op performance

All three changes are implemented and measured separately, then qualified together
on the pinned 202-project Orchard graph.

| Complete workflow | Previous | Current |
| --- | ---: | ---: |
| CSS edit | 21.854 s | **12.889 s** |
| Razor edit | 20.226 s | **12.028 s** |
| Fresh recovery, 8 connections | 34.551 s | **29.353 s** |
| No-op median, three runs | 6.698 s | **2.820 s** |
| Fresh recovery download bytes | 2,016,334,359 | **676,758,230** |

CSS/Razor edits are about **41% faster**, no-op is **58% faster**, and fresh
recovery downloads **66.4% fewer bytes**. Each edit still executes one binding
and one compilation (OrchardCore.Setup), with zero restore/discovery. Both runtime
checks return HTTP 200 and serve the new CSS/Razor markers and prior C# behavior.

After deleting producer outputs, fresh recovery hits all 202 bindings, 202
compilations, 287 package extractions, restore, discovery and composition. It
compiles nothing and downloads no extracted package files. All 3,457 application
files match, and the app runs with both source checkouts temporarily unavailable.
A separate fresh consumer at 32 connections also passes those checks, downloads
the same bytes, and takes 29.606 seconds. These single loopback samples do not
establish a benefit from changing the default connection limit.

All three no-ops execute no build/preparation actions and make no cache requests.
Every accepted Orchard case reports zero cache failures. Its producer completed
in 707.368 seconds; cold build optimization was not the objective. No concurrent
tool builds or benchmark cleanup ran during these producer/edit timings.
Workflow before/after comparisons are single samples except for the three-run
no-op medians; component experiments are described separately below.

In the current no-op, source snapshot takes 0.669 s, generation 0.501 s, Bazel
0.259 s, exit verification 0.676 s and bundle validation 0.364 s. The previous
Bazel phase took 4.108 s. On CSS/Razor edits, composition action-processing samples
fall from 7.966 / 7.968 s to 4.273 / 4.241 s. These samples are inside the Bazel
phase, not additional whole-workflow costs.


## One application tree

Project-action composition now emits `build.bundle/app` once and a separate
`build.metadata` tree containing the sealed artifact inventory and result identity.
The intermediate artifacts remain in the per-project compile outputs owned by
Bazel; composition no longer duplicates those artifacts into final `cache` and
`runtime` trees. The controller verifies the application against the sealed
metadata. Native test runfiles include both outputs, and the test runner validates
and stages the canonical application without invoking build or restore.

The legacy non-project-action bundle contract remains supported. Custom consumers
of the opt-in project-action final `cache`/`runtime` directories must use the
canonical application and metadata outputs instead.

A paired replay of the retained Orchard entry isolated this output-copy change:

| Measurement | Duplicated output | Canonical output |
| --- | ---: | ---: |
| Median direct composition, two samples | 3.392 s | 2.552 s |
| Output files, including metadata | 10,383 | 3,460 |
| Output bytes | 2,009,297,460 | 669,835,299 |

All **3,457 application files** matched byte for byte. Direct composition improved
24.8%; output volume fell 66.7%. This single-entry replay excludes dependency
validation, Bazel sandbox/action overhead and network transfers.

## Profile and tune downloads

The preceding full recovery downloaded **2,016,334,359 bytes**. Its Bazel trace
recorded 4.243 aggregate seconds in remote output download events. Analysis,
repository setup, action bookkeeping and file materialization also contribute to
fresh recovery; those categories overlap and must not be summed as wall time.

The gate now reports GET/HEAD request counts, received bytes, the connection limit,
and aggregate successful GET duration. GET duration includes queuing and transfer
through the proxy; concurrent durations overlap. It is not a separate wall-clock
phase or a measure of pure network latency.

Workflow JSON accepts `bazel-remote-connections` from 1 through 128. The default
remains **8**. Publication retains its eight-operation limit and the CAS-before-AC
barrier. A test-only download replay verifies all received content hashes.

For 128 blobs totaling 8 MiB, with two samples per setting and added server delay
per request:

| Added delay | 8 connections, median | 32 connections, median |
| --- | ---: | ---: |
| 0 ms | 0.035 s | 0.033 s |
| 20 ms | 0.438 s | 0.136 s |
| 80 ms | 1.424 s | 0.372 s |

Higher concurrency is useful in this latency-limited experiment (3.2x / 3.8x),
but this is not a bandwidth-limited WAN benchmark or a reason to change the local
default without deployment measurements.

## Avoid unchanged generated-file rewrites

The controller still captures and verifies mutable inputs. It compares generated
file bytes and leaves unchanged files intact, preserving their modification times.
Changed declarations and tampered content are rewritten. MODULE content is assembled
before one final comparison instead of being written and appended repeatedly.
This covers generated BUILD, MODULE, lockfile, Starlark, host and layout inputs.
Source snapshot and declaration-generation timings are now reported separately.

A direct Orchard Bazel experiment held source files, action code and flags fixed.
Rewriting identical generated files before each invocation gave a **3.975-second**
median. Keeping those files unchanged gave **0.204 seconds**, across three warm
samples each. This measures the Bazel invocation, excluding the controller.

A separate repository-rule experiment found little additional benefit from removing
`local = True` once generated files remained stable. That change was discarded;
repository invalidation semantics remain unchanged.

## Validation

- Warning-free tool builds, five style tests and 33 preparation tests pass.
- 69 workflow tests pass with one Linux-only skip. Coverage includes canonical
  application composition, corrupt dependency rejection, connection-limit checks,
  and repairing changed generated content even when its timestamp is preserved.
- Native four-project acceptance passes resource edits, file additions/removals,
  local/shared import changes and no-op. Updated embedded resource bytes are checked.
- The pinned Serilog .NET 10 slice passes real approval tests, producer-deleted
  remote recovery, body/API edits, and three warm runs. Deliberately failed tests
  and a live source mutation both prevent publication.
- The unmodified Serilog multi-framework attempt was rejected during discovery
  for an unqualified framework. The successful fixture narrows the library to
  `net10.0`; it does not qualify its other frameworks.

These are native macOS ARM64 / pinned Nix .NET 10.0.400 / Bazel 8.4.2 measurements.
They do not qualify cross-host cache reuse, Linux, or raw MSBuild incremental parity.

## Evidence and reproducibility

[Structured evidence](runtime-recovery-evidence.json) records the component samples,
full workflow counters, action profiles, changed projects, native invalidation
cases and Serilog test/publication outcomes. The implementation commits are
`f421198`, `ac8c5ea`, and `9615efe`.

The test bridge accepts `profile-action-downloads` with JSON fields `endpoint`,
`directory`, `connections`, and `objects` (CAS digest strings). It checks every
received blob hash. `profile-action-publication` remains available for the preceding
publication experiment. Workflow request files use the normal `owned-workflow`
command; `bazel-remote-connections` is optional and defaults to eight.

The full workflow remains scoped to the same pinned Orchard revision and macOS
loopback cache as the [preceding publication measurements](cache-publication-performance.md).
Buildifier and `git diff --check` pass. No Linux or CI workflow was dispatched.
