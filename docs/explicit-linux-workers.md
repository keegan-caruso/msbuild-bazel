# Persistent workers for explicit MSBuild rules

`linux_worker = True` opts `msbuild_library`, `msbuild_binary`, and `msbuild_test`
into the sequential Bazel JSON worker. Run with
`--strategy=MSBuildAssembly=worker --worker_max_instances=MSBuildAssembly=4`.
The initial execution platform is the pinned Ubuntu 22.04 ARM64 image with .NET
10.0.400 and bubblewrap. Fresh-process builds remain the default. Remote execution
remains disabled; action-cache hits do not start compiler workers.

The implementation follows the existing NativeProjectCache Linux broker/child
boundary. It does not use the old graph preparation or dependency replay path.
The broker validates Bazel input digests and retains a bounded, private snapshot
cache (1 GiB / 100,000 files). The sandboxed child only sees the current request's
read-only inputs, pinned SDK/tools, writable action state, and a private compiler
IPC directory. The SDK and runner are declared Bazel tools and participate in the
worker key. OS libraries and selected host files remain part of the qualified
execution platform, as in the original worker implementation.

MSBuild and Roslyn stay loaded between requests. Every build uses new
ProjectCollection/BuildManager objects. Distinct input identities use distinct
paths to prevent stale compiler metadata when file lengths/timestamps coincide.
The child restores its environment and working directory after requests. Failed
builds return errors without poisoning the next request; timeouts terminate the
child. Multiplexing and the worker cancellation protocol are unsupported.

This supports trusted build tasks. It is not isolation between mutually hostile
managed tasks in the same process. Ordinary fresh-process execution retains its
separate sandbox for each build.

## Qualification

In the pinned Linux image, build the tool and run:

```sh
bash scripts/dotnet.sh build tools/ExplicitBuild -c Release -warnaserror
python3 tests/explicit_msbuild/worker_protocol.py
RULES_MSBUILD_EXPLICIT_WORKER=1 \
  python3 tests/explicit_msbuild/acceptance.py /tmp/explicit-worker-check
RULES_MSBUILD_EXPLICIT_WORKER=1 \
  python3 tests/explicit_msbuild/mtp.py /tmp/explicit-worker-check /tmp/mtp-lock
```

The MTP package setup is described in [the explicit API documentation](explicit-bazel-rules.md).
Controls verify PID reuse, actual Roslyn server-served compilation, unchanged
reference assemblies after method-body changes, compile failure/recovery,
same-size/same-timestamp edits, undeclared reads, read-only source enforcement,
and deleted-producer relocated cache recovery. MTP pass/fail/recovery uses its
actual Microsoft Testing Platform entry point. Separate protocol controls reject
forged input digests and undeclared requests.

## Performance methodology

`tests/explicit_msbuild/perf.py` compares fresh-process Bazel, persistent-worker
Bazel, and ordinary `dotnet build` on the same generated C# binary-tree graph.
Run it on the container's native filesystem, not a Mac bind mount:

```sh
python3 tests/explicit_msbuild/perf.py /tmp/explicit-perf \
  --sizes 2,32,128 --repeats 3
```

The sizes count libraries; one executable root gives 3, 33, and 129 total
projects. Each library calls its children, and the root's result is checked after
edits. These are package-free, small-source projects intended to expose
per-project overhead and graph scaling. They are not Orchard or Razor benchmarks.

Both Bazel modes use four jobs; workers allow four processes. Raw MSBuild uses
`-m:4` with its normal compiler server. SDK acquisition, runner bootstrap,
repository downloads, and Bazel server startup/analysis are outside the timed
build calls. Clean-output samples remove build outputs and restart Bazel/compiler
servers before each sample. OS disk caches are not flushed. Unchanged and
leaf-method-body edits reuse their respective warm processes. Engines alternate
order across three repetitions; summaries report median wall time. No disk or
remote action cache is configured for this matrix. Profiles and complete logs
are retained beside `results.json` and `summary.json`.

For loopback HTTP cache timing after the matrix:

```sh
python3 tests/explicit_msbuild/remote_perf.py /tmp/explicit-perf
```

This uses a test HTTP CAS/action-cache server on loopback, seeds all project
outputs, then cleans outputs and restarts Bazel before each recovery. The measured
build follows analysis and must report remote hits with no worker execution.
There is no simulated network latency/bandwidth limit; this is a cache-client
and output-recovery measurement, not a WAN service benchmark.

## Measurements

Four vCPUs, 6 GiB RAM, native Linux filesystem; median of three runs, seconds.

| Projects | Case | Fresh Bazel | Worker Bazel | Raw MSBuild |
| ---: | --- | ---: | ---: | ---: |
| 3 | cold | 3.692 | 2.446 | 1.544 |
| 3 | unchanged | 0.095 | 0.077 | 0.647 |
| 3 | leaf-body-edit | 1.050 | 0.349 | 0.698 |
| 33 | cold | 13.482 | 11.007 | 3.725 |
| 33 | unchanged | 0.229 | 0.246 | 1.401 |
| 33 | leaf-body-edit | 1.122 | 0.385 | 1.260 |
| 129 | cold | 45.785 | 26.803 | 7.936 |
| 129 | unchanged | 0.110 | 0.106 | 3.731 |
| 129 | leaf-body-edit | 1.150 | 0.416 | 3.624 |

At 129 projects, workers reduce clean-build time **41%** versus fresh-process
Bazel (1.71× faster), but remain **3.38× slower than raw MSBuild**. Method-body
edits are **8.71× faster than raw MSBuild** and **2.76× faster than fresh-process
Bazel**. Unchanged builds are primarily Bazel's existing graph/action reuse;
workers do not materially contribute to that improvement.

The cold-build target is not achieved. The explicit path still evaluates/restores
and runs SDK targets separately per assembly, while raw MSBuild shares work across
its build graph. This experiment removes global discovery and demonstrates warm
iteration gains; it does not establish Orchard timings or Razor compatibility.

[Raw samples](evidence/explicit-linux-workers/results.json) and
[median summary](evidence/explicit-linux-workers/summary.json) are checked in.

The measured worker source is commit `c50b2ad`; the exact source hashes and
platform are in [environment.json](evidence/explicit-linux-workers/environment.json).
The following cleanup bounds SDK resolver registration to once per process;
final worker controls also run after that cleanup.

### HTTP recovery

| Projects | Median seconds | Compiler actions executed |
| ---: | ---: | ---: |
| 3 | 1.040 | 0 |
| 33 | 2.435 | 0 |
| 129 | 6.480 | 0 |

Each sample recovered every project action from the loopback HTTP cache, with
local disk caching disabled. The 129-project median is **6.48 s**, versus **26.80 s**
for worker compilation. This recovery timing includes cache lookup/download and
output materialization, but excludes the separately performed server startup and
analysis. [HTTP samples](evidence/explicit-linux-workers/remote-results.json).
