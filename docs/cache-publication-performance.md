# Cache publication and runtime composition

The 202-project Orchard workflow now publishes only missing remote content and
composes runtime outputs from smaller per-project Bazel outputs. CSS edits fall
from **53.021 to 21.854 seconds**; Razor edits fall from **49.562 to 20.226 seconds**.
Each still executes one binding and one compilation, with no restore or discovery.

## 1. Profile publication separately

The controller now records `validateBundles` and `publishActionCache` independently
of its existing Bazel and lease-verification phases. A test-only component replays
validation and publication against a retained application bundle without rebuilding
Orchard or changing production cache validation.

For 3,139 unique content blobs totaling 647,482,042 bytes, the original sequential
publication took **20.592 seconds**. Bundle validation took **0.349 seconds** and
local gate staging took **1.183 seconds**. This replay excludes action records,
Bazel execution, initial controller setup and lease verification; it does not
attribute every second outside Bazel to publication.

Reproduce the component with `Preparation.Tests.dll profile-action-publication`
and a JSON request containing `bundle` (a composed build.bundle directory),
`endpoint` (the HTTP cache URL), and `directory` (a new staging directory).
The test bridge reports validation, staging, publication and transport counters.

## 2. Reuse remote content

After acceptance, the gate checks each staged CAS object with a fresh HTTP HEAD.
Existing blobs are reused; missing blobs are uploaded. Up to eight operations run
concurrently. All CAS operations must succeed before any action record is sent.
Action records are always published, never skipped based on existence.

HTTP 405/501 falls back to upload for caches without HEAD support. Authentication,
transport and other server errors fail publication; inconsistent known content
length also fails. Local digest checks and staging limits remain enforced.
Existence information is not retained between invocations. Ordinary remote-cache
eviction after checking or publication can still produce a miss; this does not
introduce a durable-presence assumption or bypass download verification.

The same retained-payload replay now takes **0.056 seconds** for publication,
reusing every blob and uploading zero bytes. This is an all-present loopback
component case, not an end-to-end speedup claim. Actual CSS/Razor edits each
publish 25 objects and about **2.39 MB**, reusing 3,164 objects / 646.36 MB.
Publication takes **0.152 / 0.153 seconds**, respectively.

## 3. Smaller Bazel runtime outputs

Each compile action additionally emits a sealed runtime projection containing its
own DLL, PDB and XML artifacts. Bazel stores each projection as a separate tree
artifact in the compile action's cached result. Composition consumes the dependency projections plus the full entry
bundle. It validates every consumed producer, checks toolchain consistency, and
retains the existing application/cache/runtime output contract. MSBuild still
produces the artifacts and project semantics.

A paired direct replay used identical accepted Orchard compile outputs in the
order full/projected/projected/full:

| Input form | Samples | Median |
| --- | --- | ---: |
| Full dependency bundles | 4.042 / 3.342 s | 3.692 s |
| Runtime projections | 3.408 / 3.070 s | 3.239 s |

The measured direct-composition reduction is **12.3%**. Input files fall from
15,865 to **4,669** (70.6% fewer); input bytes fall from 707.05 MB to 672.32 MB.
The full entry application dominates byte volume. All **10,383 composed files**
match byte for byte and in file mode between implementations. This replay excludes
Bazel sandbox setup, action bookkeeping and cache transport.

In the complete CSS/Razor runs, Bazel's composition action-processing samples are
7.966 / 7.968 seconds, versus the preceding 10.753 / 10.214 seconds. These action
samples are broader than direct replay and must not be added to whole-workflow time.

## Complete workflow qualification

Same pinned Orchard revision `04467a3438d4255627c1a478598a1585b3ff2947`,
macOS ARM64, Nix .NET 10.0.400, Bazel 8.4.2, two jobs, Release/Production,
loopback bazel-remote, and shared verified NuGet archive repository cache as the
[resource-body baseline](resource-body-performance.md).

| Case | Previous | Current |
| --- | ---: | ---: |
| CSS edit | 53.021 s | **21.854 s** |
| Razor edit | 49.562 s | **20.226 s** |
| Fresh remote recovery | 37.809 s | **34.551 s** |
| No-op median, three runs | 6.754 s | **6.698 s** |

CSS is **2.43x faster** and Razor **2.45x faster**. Only OrchardCore.Setup binds
and compiles on either edit. Both runtime checks return HTTP 200 and serve the
new CSS/Razor content with the prior C# behavior intact.

Producer outputs and generated workspace were deleted before fresh recovery.
Recovery hits all 202 bindings, 202 compilations, 287 package extractions, restore,
discovery and composition; it compiles nothing and downloads no extracted package
files. All **3,457 application files** match the producer. The recovered application
runs and serves both edits with both source checkouts temporarily unavailable.
All three no-ops execute no build/preparation actions. Every case has zero cache
failures.

The producer passed in 700.751 seconds. Cleanup of a retired benchmark state
occurred during that run, so its cold timing is not a controlled comparison.
CSS/Razor timings had no concurrent cleanup or tool builds. Workflow comparisons
are single samples against the preceding baseline; the direct composition replay
uses two samples per variant. No-op remains broadly unchanged. These measurements
do not establish raw MSBuild incremental-edit parity, cross-host cache correctness,
WAN performance, or Linux qualification.

## Validation and evidence

- Warning-free owned-tool builds; five style tests and 33 preparation tests pass.
- 67 workflow tests pass with one Linux-only skip, including cache reuse,
  rechecking after eviction, unsupported HEAD fallback, wrong-size rejection,
  parallel publication ordering and failure barriers, plus corrupt runtime inputs.
- Buildifier and `git diff --check` pass.
- Structured measurements: [cache-publication-evidence.json](cache-publication-evidence.json).

Runtime composition still creates the complete entry output and the gate still
stages/validates all Bazel uploads locally. The improvements remove redundant
remote transmission and narrow dependency inputs without removing those checks.
