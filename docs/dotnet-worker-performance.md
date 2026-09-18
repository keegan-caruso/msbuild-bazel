# .NET worker cache: correctness and performance

Candidate `3c6b975998dc7ac421704e4cd08d23cbec79f1d5`, measured on macOS 27.0.0
(26A428), Apple M4 ARM64, 10 logical CPUs; pinned SDK 10.0.400, Bazel 8.4.2
and bazel-remote 2.6.2. These are same-host loopback measurements, not separate
worker acceptance or LAN timings.

All 24 completed comparisons passed exact managed DLL/PDB equality and actual
application/approval-test execution. Cache recovery avoided compilation on
unchanged inputs and compiled only one project for implementation edits. **None
of the six warm/edit median comparisons met the diagnostic performance target.**

## Three-repetition medians

Times include build and application/test execution. Raw MSBuild retains local
incremental state for unchanged/edit cases. The adapter starts with a fresh
checkout, preparation state and Bazel directory, using a remote snapshot whose
producer was deleted. Empty-cache cases start both paths fresh. Restore and tool
acquisition are excluded from both. See the [protocol](dotnet-worker-measurement-protocol.md).

| Workload | Case | Raw MSBuild (s) | Adapter (s) | Adapter/raw | Adapter compiles |
|---|---|---:|---:|---:|---:|
| Diamond, 4 projects | Unchanged | 0.578 | 8.460 | 14.64x | 0 |
| Diamond | Body edit | 1.004 | 9.105 | 9.07x | 1 |
| Diamond | API edit | 1.477 | 10.315 | 6.99x | 4 |
| Diamond | Empty cache | 1.960 | 12.857 | 6.56x | 4 |
| Serilog approval, 2 projects | Unchanged | 1.064 | 12.861 | 12.09x | 0 |
| Serilog | Body edit | 1.187 | 15.302 | 12.89x | 1 |
| Serilog | API edit | 1.218 | 16.977 | 13.94x | 2 |
| Serilog | Empty cache | 1.274 | 17.599 | 13.81x | 2 |

The diagnostic target is adapter <= 1.25 * raw + 0.250 seconds for warm/edit
cases. Cold overhead is reported without a pass threshold. Small graphs and an
interactive host limit generalization; Serilog samples vary substantially
(e.g. API 16.65–29.25 seconds). No larger-project speedup is established here.

## Where the time goes

For unchanged diamond recovery, median identity validation takes 1.34 s, final
lease checks 2.32 s, and the Bazel startup/action phase 4.38 s. Preparation is
0.24 s. Serilog's corresponding costs are 1.42 s, 2.63 s, 6.33 s and 0.70 s.
These are individually calculated phase medians, so they need not sum to the
median wall time. The Bazel phase includes actions and tests; it is not a direct
measurement of startup alone.

Median summed HTTP request time is only 0.036 s for unchanged diamond and
0.061 s for unchanged Serilog. This loopback result makes repeated validation
and Bazel overhead the next local targets, while saying little about WAN latency.
Preserve content checks and mutation rejection when sharing identity work;
profile the Bazel phase before attributing all of it to process startup.

## Transport accounting

Median payload bytes and GET/HEAD/PUT counts, excluding headers and TLS:

| Workload/case | Download bytes | Upload bytes | GET / HEAD / PUT |
|---|---:|---:|---|
| Diamond unchanged | 182,024 | 6,638 | 13 / 13 / 2 |
| Diamond body | 169,193 | 6,635 | 12 / 13 / 2 |
| Diamond API | 169,193 | 6,626 | 12 / 13 / 2 |
| Diamond empty | 0 | 182,023 | 0 / 13 / 13 |
| Serilog unchanged | 4,638,881 | 136,339 | 33 / 55 / 2 |
| Serilog body | 4,430,577 | 136,331 | 32 / 55 / 2 |
| Serilog API | 4,430,577 | 136,305 | 32 / 55 / 2 |
| Serilog empty | 0 | 57,044,627 | 0 / 55 / 55 |

Nonempty cases share a service and select the original producer snapshot;
previous repetitions can deduplicate publication via HEAD, so upload medians
are not first-publication costs. Every empty case uses a new service. Consumer
local state is always fresh. All measured transport failure counters were zero.
The service stores inner native snapshot CAS objects, not Bazel Action Cache
entries; remote execution remains disabled.

## Reproduction and evidence

Run in the pinned Nix environment, with the release binary matching
`tests/remote_workers/bazel-remote.json`, a restored global NuGet cache and the
pinned Serilog checkout:

```sh
python3 tests/remote_workers/measure.py --cache-binary "$CACHE_BINARY" \
  --packages "$PACKAGES" --checkout "$SERILOG_CHECKOUT" \
  --output "$RESULT_DIRECTORY" --repetitions 3
python3 tests/remote_workers/summarize.py "$RESULT_DIRECTORY/report.json" \
  --output "$SUMMARY_FILE"
```

[Compact evidence](dotnet-worker-performance-evidence.json) retains all 24
samples, phase/counter measurements, production revision, harness hashes and
input report hashes. The input labels identify retained experiment reports;
they are not required machine paths. `wm1` contributed 12 passing diamond samples
before a Serilog comparator PathMap failure; `wm2` contributed all 12 passing
Serilog samples after the comparator correction. The protocol records that fix
and the preflight work-set correction. Failed samples are excluded explicitly,
not relabeled as passing. Performance thresholds were unchanged.

[Real-service acceptance](independent-remote-cache.md) separately records cache
recovery and failed-test publication controls. The harness rejects same-machine
producer/consumer handoffs by default. Actual second-worker execution still
requires a compatible second macOS ARM64 host; issue #42 remains unproven.

## Final validation

`scripts/check-dotnet.sh` passed owned .NET builds/style/warnings checks and the
5 style-policy, 32 preparation and 20 workflow tests. `scripts/check.sh` passed
toolchain and Starlark checks. Harness Python compilation and `git diff --check`
passed. No GitHub CI was run.
