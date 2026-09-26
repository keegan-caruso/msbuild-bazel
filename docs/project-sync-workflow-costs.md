# Generated-graph workflow costs

This stage measures the complete generated Orchard CMS graph (202 projects) and
separates package acquisition, synchronization, compilation, edits and independent
HTTP-cache recovery. It is not a benchmark of the whole runtime or ASP.NET repository.

## Protocol

- Orchard commit `04467a3438d4255627c1a478598a1585b3ff2947`, SDK 10.0.400,
  Bazel 9.2.0, Release/net10.0, Linux ARM64.
- One active build VM: 6 CPUs / 10 GiB on a 10-CPU / 16-GiB macOS host. A separate
  1-GiB cache VM remains available. Stop the producer before consumer measurements.
- Both build systems get two build slots. Bazel gets two persistent workers and
  a 4096-MB soft process-tree budget, shrinking the pool and polling every second.
  This bounds retained worker/compiler memory; it is not a hard limit on all VM RAM.
- Cold compilation means clean build outputs and stopped build/compiler servers,
  with SDK/package downloads already present. Raw restore is forced and measured
  separately over the downloaded NuGet cache; raw build uses `--no-restore`.
  Bazel includes declared package extraction, runner bootstrap and SDK runtime
  composition. Ordinary incremental builds retain the server and workers.
- Local compilation measurements disable HTTP and disk action caches. Body edits
  change a method's implementation; API edits add a public property. Source bytes
  are restored between samples. API restoration is followed by a clean sample,
  so there is no need to rebuild that final revert solely for measurement.
- Repeated samples include process/client startup and execution-log writing. No
  concurrent builds or tests run in the build VM. Filesystem caches remain warm;
  these are not first-ever downloads or hardware-isolated laboratory results.

An exploratory unbounded sequence completed one cold/body/API series but exhausted
available VM memory during its API revert. At diagnosis only about 380 MiB remained
available, with roughly 5 GiB of shared memory. The VM required restart; that
sequence is excluded from the normal benchmark. Disk reclamation also overlapped
its first API sample. Do not interpret its 165.7-second API observation as a clean
comparison. Logs and phase totals were preserved before recovery.

## Reproduce

Prepare the generated and restored source workspaces using
[the broader-graph qualification](project-sync-broader-graphs.md), then run
sequentially in the same VM:

```sh
python3 tests/project_sync/upstream/workflow_benchmark.py \
  GENERATED_ORCHARD RAW_ORCHARD OUTPUT --phase bazel --repetitions 2
python3 tests/project_sync/upstream/workflow_benchmark.py \
  GENERATED_ORCHARD RAW_ORCHARD OUTPUT --phase raw --repetitions 2
```

The driver preserves logs, execution logs, Bazel profiles and JSON timing records.
It restores source/mapping/generated files in `finally` and shuts down servers.
Optional `--profile-control` alternates detailed MSBuild profiling on/off for
attribution; leave it off for ordinary performance measurements. Profiling is
already opt-in in the production rules.

Independent acquisition and recovery use `cache_packages.py` and `remote_graph.py`
from the same directory. Every recovery requires an absent output base, disables
consumer uploads and disk caching, verifies all action hits/output hashes, and
smoke-tests the recovered application. Guest network byte-counter deltas include
repository acquisition and protocol overhead, not just CAS payload bytes.

## Matched local results

Two complete repetitions per build system, in seconds. Medians for two samples
are their midpoint; the ranges are retained because this is a small sample.

| Case | Bazel samples | Raw samples | Median comparison |
| --- | --- | --- | --- |
| Cold build | 159.633, 165.115 | 63.704, 70.550 | Bazel 2.42× raw build time |
| Warm no-op | 0.535, 0.632 | 11.454, 10.883 | Bazel 19.1× faster |
| Body edit | 2.314, 3.821 | 11.195, 10.725 | Bazel 3.57× faster |
| API edit | 127.153, 138.356 | 28.000, 27.074 | Bazel 4.82× raw build time |

Raw forced restore costs 3.673 / 3.471 seconds separately. Adding that cost to
raw cold build narrows the cold ratio to about 2.30×. Both Bazel cold runs execute
202 compilations, 287 package extractions, one SDK-runtime composition and one
runner bootstrap. No-op executes none; body edits compile one project; API edits
compile 193. These are build measurements; Orchard has application smoke checks,
not a Bazel unit-test target in this graph.

The API result is a substantial remaining weakness. A warm body edit's speedup
must not be presented as the speedup for an arbitrary project edit. A memory
budget can recycle compiler workers and adds variation to short edits.

Initial synchronization in the bounded series takes 34.947 seconds, including
package extraction and generator bootstrap. The following unchanged checks take
16.514 / 15.459 seconds. Downloaded archives were already present; this is separate
from feed acquisition.

## Attribution and next costs

The preserved diagnostic cold run records these cumulative values across 202
projects. They overlap across two workers and nested MSBuild tasks, so **do not
add them to obtain wall time** or subtract them directly from the bounded result.

| Work | Cumulative seconds | Interpretation |
| --- | ---: | --- |
| C# compiler tasks | 104.35 | Largest measured MSBuild task cost |
| Worker input snapshots | 32.35 | Includes verification/linking and filesystem preparation |
| Restore + build evaluation | 21.37 | Configured SDK evaluation remains per project/action |
| Restore requests | 19.08 | Includes nested MSBuild and NuGet tasks |
| Package extraction actions | 22.65 | Bazel cumulative action time; separate from compiler tasks |
| Worker identity/cleanup | 8.97 | Request identity and clearing previous request trees |
| MSBuild Copy tasks | 9.31 | Nested within build-request time |

Incremental body and API edits are the primary performance scorecard. Preserve
the body-edit improvement; prioritize the API-edit regression over cold-build work.
Keep native worker-memory controls on large graphs. Next investigate compiler
state reuse during API invalidation, then repeated input-tree materialization and
restore/evaluation costs. Preserve the reference, test, read-only-input and remote
recovery contracts while removing repeated work. Do not weaken digest checks to
improve a snapshot microbenchmark.

A one-worker control under the same 4096-MB budget took **183.724 seconds cold**
and **142.095 seconds for the API edit**, versus the two-worker ranges above.
It also measured 0.484-second no-op and 2.528-second body edit. This single control
provides no reason to replace two workers for this graph: lost parallelism did not
pay for itself through reduced compiler duplication. The normal driver retains
two workers; `--workers 1` remains available for future comparisons.

## Retained synchronization improvement

Use one `ProjectCollection` per synchronization invocation to share parsed MSBuild
and SDK XML. Keep separate evaluated projects for each global-property set; do not
reuse evaluated/build results across invocations. This removes repeated document
loading while preserving framework, package-lock and property boundaries.

Unchanged Orchard sync checks before the change took **16.514, 15.459 and 16.172
seconds** across the bounded and one-worker control runs. After one excluded
bootstrap warmup, the candidate took **8.686, 8.347 and 8.392 seconds**. Median
wall time falls **48.1%**, from 16.172 to 8.392 seconds, well outside the observed
sample ranges. All candidate checks preserve the generated file's SHA-256.

The focused suite includes different project globals sharing one props file,
framework overrides, package-view changes, and fresh import contents on the next
invocation. No input validation, document contract, sandbox or cache identity is
relaxed. Reproduce candidate checks with:

```sh
python3 tests/project_sync/upstream/sync_benchmark.py \
  GENERATED_ORCHARD OUTPUT_BASE REPORT.json --repetitions 3
```

The first warmup is recorded separately. Comparison baselines must use the same
source, mappings, SDK and resource settings; build the control generator before
switching implementations. This improvement affects explicit local synchronization,
not ordinary builds of already-committed generated files.


## Correctness after the optimization

The owned .NET/style checks pass, including 51 sync/name tests. The complete
mutation and cache-reversion matrix passes again on Bazel 8.8.0 and 9.2.0.
Fresh HTTP execution retains all 714 exact raw-MSBuild outcomes; Immutable retains
22,544 normalized outcomes and its loaded-source assembly hash probe. Avalonia
and Orchard synchronization retain their existing generated bytes.

The retained HTTP/Immutable workspaces predated stage 5's compiler-item-order
fix. A control generator built from the pre-optimization commit `f1801cb`
regenerated them first: only item-list ordering changed (44 HTTP and 22 Immutable
declarations). The optimized generator then produced exactly the control's bytes.
This migration is separate from the shared-document optimization; no test-name
normalization was added.

The next proposed performance gate is to reduce API edits below 2× raw while
retaining the body-edit advantage on this same graph/resource protocol, without
regressing remote recovery or correctness. Cold build below 1.5× raw is secondary. These are future targets, not achieved results.
Re-run paired samples after each candidate; a result inside the existing variation
is insufficient evidence to retain a more complex optimization.


## Independent recovery and transfer costs

The producer was stopped throughout. A fresh container with no mounts used a
new workspace path, independently downloaded all **287 package archives**
(**454,042,134 bytes in 23.808 seconds**), and had its image's installed SDK
hidden. Bazel acquired the declared SDK. Every sample used a fresh output base,
disabled local disk caching and uploads, then shut down its server. The seed used
the qualified graph's opt-in profiling setting; cache hits execute no compiler.

The first full-download recovery took **31.912 seconds**, receiving 1.388 GB,
including first-use repository acquisition. Keep it separate from the following
matched samples, which reuse downloaded repository archives but no action outputs:

| Download mode | Recovery seconds | Received bytes per recovery | Subsequent sync check seconds |
| --- | --- | --- | --- |
| `all` | 23.570, 22.613 | 1,107,950,422 / 1,107,896,984 | 10.426, 9.983 |
| `toplevel` | 22.248, 22.447 | 1,074,703,312 / 1,074,749,146 | 10.442, 11.054 |

All five recoveries have **491/491 remote action hits**, **21,223 identical
application runfiles**, four passing HTTP endpoints and three exact raw-MSBuild
asset hashes. Full downloads materialize all 4,528 recorded output hashes;
top-level downloads materialize 4,319, each matching the seed. The application
runfile comparison remains complete in both modes. Sync's declared tool action is
also a remote hit; evaluation itself still runs locally.

Top-level downloads reduce recovery traffic only about **3.0%** and median build
recovery by **3.2%** here. A later sync downloads additional tool inputs (about
26.4 MB versus 6.6 MB), narrowing the complete workflow's saving further. Keep the
benchmark's full-download default and make no production-policy change from this
small comparison. Reducing the declared runtime payload is a separate design
problem. These are guest network counters, including protocol/repository traffic;
local HTTP-cache speed is not a WAN latency or remote-execution result.

Compact measurements and validation counts are in
[the evidence record](project-sync-workflow-costs-evidence.json).
