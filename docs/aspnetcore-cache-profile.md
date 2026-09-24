# ASP.NET Core cache overhead profile

The 220-project / 275-framework-target workload now reuses declared package
artifacts when composing runtimes instead of publishing the same package files
from every assembly. Extraction also uses the .NET runtime rather than the full
SDK. The cache harness allows concurrent cache work independently of its local
CPU execution limit.

## Controlled cache comparison

Ubuntu 22.04 ARM64, four VM CPUs, 8 GiB, SDK 10.0.400, Bazel 9.2.0,
private host HTTP cache, no disk action cache, all outputs downloaded. Three
alternating original/final runs used fresh output bases in the same warm VM,
with identical trace/BEP instrumentation and warm repository download caches.
Every run recovered 578 actions (278 assemblies and 300 package extractions),
with zero compilation/extraction execution.

| Configuration | Samples (seconds) | Median |
|---|---|---:|
| Original rules, `--jobs=2` | 15.57, 15.28, 15.09 | 15.28 s |
| Final rules, `--jobs=32 --local_resources=cpu=2` | 11.52, 11.08, 11.39 | 11.39 s |

**25.5% less wall time, or 1.34× as fast.** Local execution retains two CPU slots;
32 is the number of pending actions, not 32 concurrent MSBuild processes.
The worker instance limit remains two per configuration.

A separate, newly created Linux VM recovered the final outputs in **15.23 s**
after the producer VM was deleted. Its checkout and rules paths differed from
the producer. All 4,708 selected assembly output files matched exactly. It also
reconstructed all 11,325 package runtime files byte-for-byte from cache-recovered
package artifacts. Uploads and disk caches were disabled for the consumer.

The earlier 29.43 s independent recovery used a large JSON execution log. The
new harness uses BEP counters instead. Do not attribute that entire difference
to production rule changes; the alternating comparison above controls the
instrumentation difference.

## Cold compilation

A matched warm-repository comparison used fresh output bases, cache reads disabled,
cache uploads enabled, and two local CPU slots for both configurations:

| Configuration | Cold wall time |
|---|---:|
| Original rules, two pending jobs | 141.24 s |
| Final rules, 32 pending jobs | 129.91 s |

This is approximately **8% faster**, based on one observation per configuration,
not a repeated cold-build median. The final build still executes all 300 package
extractions and 278 assemblies. Cold compilation remains substantially slower
than the earlier 44.55 s raw-MSBuild baseline, which did not upload an action cache.
These changes primarily improve remote-cache recovery; they do not close the
cold compilation gap.

The initial step-by-step profiling runs were 150.08, 158.55, and 153.49 s. They
used the old two-job cap, and the first run also warmed repository downloads.
They identify specific costs but are not the final matched cold comparison.

## What each experiment found

### 1. Repeated runtime outputs

Across all 278 assembly actions (including three execution-configuration tools):

| Published runtime trees | Original | Final |
|---|---:|---:|
| Files | 15,222 | 4,175 |
| Bytes | 1,213,032,703 | 181,861,915 |

The change removes **85.0% of runtime output bytes**. Exactly 11,325 removed
package files, totaling 1,033,633,600 bytes, were reconstructed and checked against
the original published hashes. New manifests account for the difference between
removed copies and the net file-count reduction.

MSBuild still performs its normal SDK build, including copy targets and custom
post-build targets. The runner validates copied package bytes before replacing
published copies with package ID/version/relative-path references. Launchers,
project-built analyzers, and bound MSBuild tasks compose their declared package
closure when consumed. Package-version precedence, private dependency runtime
flow, collisions, and read-only worker inputs remain enforced. Native/content
files that are not classified by `ReferenceCopyLocalPaths` remain normal outputs.

At the original two-job cap, fresh recovery decreased from 17.89 s after the
extraction-input change to 15.04 s after this change (single observations).
In representative repeated runs, VM network receive bytes decreased from
approximately 1.83 GB to 1.35 GB. These are whole-VM network counters; output
sizes above come from direct file inventory. CAS deduplication means saved
output bytes and saved network bytes are not the same quantity.

### 2. Oversized extraction inputs

The 300 extraction actions declared the full SDK even though they only execute
a managed archive-extraction program. Their recorded aggregate sandbox filtering
and filesystem setup fell from **16.02 s to 0.98 s** after narrowing inputs to
`dotnet`, `host/`, and `shared/Microsoft.NETCore.App/`. Separately declared Nix
runtime/import closures remain included. Compilation keeps the complete SDK.

The corresponding single fresh-cache observations were 18.89 → 17.89 s.
Extraction payload bytes did not change. Rebuilt implementation DLL/PDB bytes
are not universally deterministic: an extraction-only full rebuild differed in
56 files, so byte identity is not claimed for every cold compilation. Raw
reference metadata and resource parity are verified separately below.

### 3. Transfer, materialization, and diagnostic overhead

A diagnostic `--remote_download_outputs=minimal` control reduced the initial
18.89 s recovery to 9.47 s. It does **not** provide equivalent materialized
outputs and is not used for the claimed speedup. It established that output
recovery was a substantial part of the cost.

Allowing more pending cache work, with two local CPU slots, reduced the single
final recovery from 15.04 to 12.83 s. Repeated controlled results are above.
All outputs are still downloaded. The default in the large-graph HTTP harness is
now 32 jobs; the rules do not impose a global Bazel concurrency setting.

Diagnostics comprise approximately 51 MB, much smaller than package outputs.
They remain available. The harness no longer serializes every action's entire
input list into the approximately 1.2 GB JSON execution log merely to count
cache hits. BEP action/runner counters verify all 578 remote hits instead.

Representative repeated BEP phase measurements show analysis staying around
1.8–1.9 s and execution decreasing from 12.05 to 7.75 s. Client/server startup
and command initialization account for additional wall time. Trace task totals
overlap across threads and nested operations; they must not be added together
or treated as a serial wall-time split. More concurrency can increase aggregate
wait time while reducing elapsed time.

## Validation and limits

- Repository .NET build, formatting, unit tests, toolchain/Starlark checks, and
  `git diff --check` passed.
- 21 explicit acceptance cases, 14 package-semantics cases, eight analyzer cases,
  ten task-binding cases, nine project-output cases, and five NuGet SDK cases
  passed, including independent cache recovery controls.
- Two additional unit controls reject undeclared runtime packages and path escapes.
- All 275 assemblies retain matching raw-MSBuild resources. All 99 available raw
  reference assemblies match inspected type/method/field metadata after the
  existing generated file-local path-hash normalization; 95 are byte-identical.
- Full upstream test execution, native/Java/Node builds, deployment packaging,
  and Bazel-owned upstream bootstrap generation remain outside this workload.
- This measurement qualifies Linux ARM64 and Bazel 9.2.0. It does not provide
  new platform or Bazel 8.8 timing evidence.

## Reproduction

Prepare the pinned workload using [the qualification instructions](aspnetcore-large-graph.md).
Use a distinct output base for each run and stop other builds while timing:

```sh
export RULES_MSBUILD_BAZEL=/absolute/path/to/bazel-9.2.0
python3 tests/explicit_msbuild/aspnetcore/profile.py \
  /work/bazel /work/fresh-base /work/results/cache.json \
  --cache http://CACHE_HOST:8099 --cache-only --jobs 32
```

For a cold producer, omit `--cache-only` and append
`-- --remote_accept_cached=false`. Both commands retain two local CPU slots.
The harness records wall time, phase traces, BEP metrics, network counters, and
runner counts, then shuts down the Bazel server. For independent byte recovery,
use `remote.py --seed` and then `remote.py` in a separate consumer; compare their
`hashes` dictionaries. Use `--jobs 2` for the original concurrency control.

[Machine-readable measurements](aspnetcore-cache-profile-evidence.json) retain
single-factor observations separately from the repeated comparison.
