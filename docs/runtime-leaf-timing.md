# Runtime dependency body-edit timing

The original Bazel capture measured a `System.IO.Pipelines` implementation-body edit while building the full
seven-suite target set from the [runtime closure qualification](runtime-loaded-closure.md).
Each edit adds a uniquely tagged `GC.KeepAlive` call in the `PipeOptions`
constructor. The public contract does not change. All six edits actually compile;
unique source contents prevent reuse of a previously cached edited result.

## Raw MSBuild comparison

The follow-up raw control uses the same runtime commit, SDK 10.0.400, Linux ARM64
container allocation (8 CPUs / 16 GiB), Release configuration and body-only edit.
Three unique edits per mode produced these command wall times:

| Mode | No-op median | Body-edit samples | Body-edit median |
| --- | ---: | --- | ---: |
| Raw MSBuild, shared compiler | 10.761 s | 11.166 / 11.276 / 11.274 s | **11.274 s** |
| Raw MSBuild, fresh compiler | 10.865 s | 12.144 / 12.377 / 12.172 s | 12.172 s |
| Bazel, retained server/worker (prior capture) | 0.167 s | 4.985 / 3.426 / 3.361 s | **3.426 s** |
| Bazel, batch process (prior capture) | 5.581 s | 9.586 / 10.235 / 10.456 s | 10.235 s |

The recorded retained-worker Bazel median is **3.29× faster** than raw MSBuild
with its compiler server enabled; batch Bazel is **1.10× faster**. These are
separate captures of this warm slice, not simultaneous trials or a general
speedup claim. The raw no-op already takes 10.76 seconds; compilation alone does
not account for most of its wall time.

### What the raw command builds

One generated MSBuild traversal requests `Build` for the **38 configured roots**
from the cumulative qualification selection, retaining each root's target
framework and normal upstream project references. It covers the seven test
assemblies and the source-built managed host dependencies. All **129 expected
outputs** exist: 121 shared managed assemblies, the private formatter and seven
test assemblies. Timing only the seven test projects would omit independently
selected runtime implementations.

Each command uses `dotnet msbuild -t:Build -m:2 -nr:true`, with the qualification's
Linux/ARM64/Release properties and `UseLocalTargetingRuntimePack=false`.
`UseSharedCompilation` is the only compiler-mode difference. Binlogs confirm
that the shared mode actually used the compiler server. Package restore and
first-time compilation occur before measurement; the timed command does not
restore or run tests. The shared compiler is already warm after its priming build.

All six raw edits invoke **only Pipelines' Csc task**. Every no-op invokes no
compiler. The public reference hash stays unchanged, each edit changes the
implementation hash, and restoring the source restores the original output hashes.
The upstream Git working tree is clean after capture. Binlog-reader execution and
hash checks are outside command timing; binlog writing is inside it.

### Comparison limits and evidence

Raw timing covers managed build outputs. It does **not** rebuild/check the native
products or compose the test-host layout; Bazel checks those actions and updates
the runtime layout. This gives the raw control a narrower boundary, not additional
work charged to MSBuild. Neither capture measures cold builds or test execution.

An optional same-session Bazel refresh unexpectedly rebuilt baseline outputs and
was stopped during priming, before any accepted samples. Its log is retained for
diagnosis; no result from that invocation is included. The comparison above uses
the original successful Bazel measurements, with their existing limits.
The later [cache diagnosis](runtime-cache-diagnosis.md) identifies the accidental
Bazel 8.4.2 selection and records a successful repeat with verified 9.2.0.

See [raw samples, commands, hashes and compiler evidence](runtime-raw-leaf-timing-evidence.json).
Full binlogs, reports and exact measured drivers are retained locally under
`/private/tmp/runtime-raw-leaf-timing-evidence`, with the raw capture archived at
`/private/tmp/runtime-raw-leaf-results.tar.gz`. The raw checkout and outputs remain
in the stopped producer container for follow-up work.

### Reproduce the raw capture

Use the pinned upstream checkout and cumulative inventory from the
[loaded-closure qualification](runtime-loaded-closure.md). Prime its configured
roots using the existing `subset_prepare.py` raw build commands first. The
inventory's adjacent `selection.json` supplies the traversal roots. Use a new
report directory outside the upstream checkout:

```sh
python3 tests/explicit_msbuild/runtime/raw_leaf_timing.py \
  SOURCE INVENTORY_JSON NEW_REPORT_DIRECTORY --shared-compilation true
```

`RULES_MSBUILD_DOTNET_ROOT` must select SDK 10.0.400. Repeat with a different report
directory and `--shared-compilation false` for the fresh-compiler control. The
harness builds its binlog reader before timing, captures three no-ops and three
unique edits, verifies contract/implementation hashes, and restores the source
in a `finally` block.

## Original Bazel results

End-to-end command wall time, with the graph and dependencies already built:

| Mode | No-op median | Body-edit samples | Body-edit median |
| --- | ---: | --- | ---: |
| Fresh Bazel process per invocation (`--batch`) | 5.581 s | 9.586 / 10.235 / 10.456 s | 10.235 s |
| Retained Bazel server and worker | 0.167 s | 4.985 / 3.426 / 3.361 s | 3.426 s |

The first retained-server edit starts the MSBuild worker. The next two edits use
the warmed worker and take **3.36–3.43 seconds**. Its no-op samples are 0.216,
0.167 and 0.117 seconds. The final warm trace attributes 2.966 seconds to the
Pipelines assembly action and 0.138 seconds to updating the runtime host layout;
Bazel reports a 3.12-second critical path and 3.275-second elapsed time, versus
3.361 seconds for the complete command.

Every edit recompiles **only Pipelines**: no other managed producer or native
producer compiles, and no tests execute. Public reference bytes remain unchanged.
Restoring the source reuses cached outputs; the restored implementation and
contract hashes match the qualified producer seed. The build still updates the
runtime layout consumed by the seven test targets.

See [per-sample evidence](runtime-leaf-timing-evidence.json). Full execution logs,
Bazel JSON trace profiles and the exact measured harness are retained locally in
`/private/tmp/runtime-leaf-timing-evidence`.

## Conditions and limits

Linux ARM64, 8 CPUs, 16 GiB RAM, pinned SDK 10.0.400 and Bazel 9.2.0. The existing
273-node configured runtime fixture supplies the seven top-level test targets.
Commands use `bazel build`, two jobs, one persistent MSBuild worker, HTTP cache,
no disk cache, all remote outputs materialized, and no upload of local results.
Batch mode restarts Bazel and its worker each invocation; both modes retain the
output base and dependency artifacts. Preparation, discovery, result parsing and
container startup are outside the timed commands. Profile/log generation is
inside the command timing.

The original capture used one machine and three edits per mode, with no concurrent
qualification build. The follow-up above adds a raw-MSBuild control; neither
capture supplies a cold-build measurement.
The container left its exited Bazel server as an unreaped zombie, causing the
post-measurement shutdown command to time out. That cleanup occurs outside all
samples; all 16 build commands completed, and the container was then stopped.
The reusable driver now bounds that cleanup separately.

## Reproduce

After preparing and priming the qualified runtime workspace:

```sh
RULES_MSBUILD_BAZEL=/tmp/bazel-9.2.0 \
python3 tests/explicit_msbuild/runtime/leaf_timing.py \
  WORKSPACE OUTPUT_BASE NEW_REPORT_DIRECTORY --cache CACHE_URL
```

The driver records three unique edits and three no-ops per mode, plus priming and
restoration. It asserts the single-producer rebuild, unchanged public reference,
changed implementation, no test execution and restored outputs. A `finally`
block restores the source even if a measurement fails.
