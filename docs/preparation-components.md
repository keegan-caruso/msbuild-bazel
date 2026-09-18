# Split preparation objects and shaped-network measurements

The v3 portable preparation format separates source-directory groups, top-level
preparation metadata groups, package objects, and non-workspace discovery evidence
into independent SHA-256 CAS objects. Publication checks object presence with HEAD
before uploading bytes. The explicit immutable root still records the current
path-bound certificate, workspace evidence, object inventories, directory modes,
and complete payload hash.

An edit replaces the affected source group and any changed generated metadata.
Unchanged groups and SDK/tool evidence are reused. Package reconstruction continues
to prefer verified local NuGet bytes. Fresh consumers currently download all
non-package components; this change reduces repeated publication, not their
required download set. Directory grouping avoids a request per source file but
adds requests compared with the v2 single preparation archive.

Transport changes do not broaden qualification. Consumers verify every object
hash and file inventory, restore exact certificate evidence before validation,
and verify the complete reconstructed payload and graph/certificate binding.
Current-input leases, source refresh admission, host compatibility, and final
publication checks still apply. v2 preparation snapshots miss conservatively;
there is no implicit mutable latest pointer. This remains the selected macOS
ARM64/Nix slice, not cross-host qualification.

## Network experiment

`probe_nuget_cache.py` accepts `--delay-ms`, `--download-mbps`,
`--upload-mbps`, and `--measurements-only`. Zero bandwidth means unlimited.
The loopback HTTP server uses a single shared byte budget per direction across
concurrent requests, pacing 64 KiB payload chunks. Delay is added once per HTTP
request. It does not simulate TCP congestion, TLS, packet loss, or remote CPU.
These are controlled shaped-loopback measurements, not observations from a WAN.

The measured cases are unchanged Serilog, one body edit, and a PolySharp upgrade.
Each consumer has fresh source/build/controller state and an independent restored
NuGet global cache. Producer files are deleted before consumption. Restore,
producer seeding, and package-fallback validation are outside consumer timings;
normal Build/Test, validation, downloads, and publication are included. The
package upgrade is currently outside preparation-reuse qualification and falls
back to fresh preparation and two compiles; it is not a preparation-cache hit.

Example consumer measurement command (inside the pinned Nix development shell):

```sh
python3 tests/preparation_reuse/probe_nuget_cache.py \
  --checkout /path/to/pinned-serilog --packages /path/to/restored-packages \
  --output /private/tmp/unique-network-run --repetitions 3 --measurements-only \
  --delay-ms 40 --download-mbps 100 --upload-mbps 20
```

The presence check is an upload optimization, not authentication of server bytes.
Downloads always verify hashes. A same-size corrupt object is rejected on download;
HEAD alone cannot detect or repair it. The format permits the offline `pack()`
helper to keep non-package files inline; normal HTTP publication splits them.

## Validation

The preparation unit suite covers unchanged component reuse, edits limited to
one source group, complete reconstruction, missing objects, bad object hashes,
wrong file contents, incomplete ZIP inventories, path escapes, overlapping paths,
expanded-size bounds, and SDK evidence reconstruction/reuse/corruption. Existing
portable-certificate and current-input controls remain in the suite. The network
unit tests verify a shared limiter with concurrent calls and actual concurrent
HTTP downloads; invalid negative or non-finite profiles reject.

Real Serilog controls cover unchanged/body/API edits, package upgrades, missing
and modified global-cache inputs, corrupt remote package recovery, failed tests,
and input mutation during the lease. Failing build/input cases publish nothing.
Network runs additionally check current runtime hashes and actual upstream tests
for every successful consumer, using three repetitions per case and profile.

## Measured results

Pinned Serilog revision `49b5339ce85385dc52d4d8e8f2b8308becf23506`, macOS
ARM64, .NET 10.0.400, Bazel 8.4.2. Each cell is the median of three fresh
consumers; versions were run sequentially, not simultaneously. The baseline is
`6a333bf` with the same shaping server and measurement options. Small timing
differences are not evidence of a broad performance improvement.

| Download/upload; request delay | Case | v2 seconds | v3 seconds | Compiles |
|---|---|---:|---:|---:|
| 100/20 Mbps; 40 ms | unchanged | 12.92 | 13.02 | 0 |
| 100/20 Mbps; 40 ms | body | 13.87 | 14.13 | 1 |
| 100/20 Mbps; 40 ms | package | 15.87 | 16.00 | 2 |
| 20/5 Mbps; 80 ms | unchanged | 15.76 | 15.58 | 0 |
| 20/5 Mbps; 80 ms | body | 17.26 | 16.90 | 1 |
| 20/5 Mbps; 80 ms | package | 21.77 | 21.89 | 2 |

Transfer medians for the 100/20 Mbps profile (decimal MB):

| Case | Upload v2 → v3 | Download v2 → v3 | HTTP requests v2 → v3 |
|---|---:|---:|---:|
| unchanged | 0.866 → 0.224 | 4.257 → 4.262 | 28 → 96 |
| body | 1.025 → 0.530 | 4.098 → 4.103 | 28 → 100 |
| package | 3.393 → 3.393 | 4.098 → 4.103 | 6 → 40 |

Unchanged publication sends **74.1% fewer bytes**; the body edit sends **48.3%
fewer bytes**. Download volume is nearly unchanged (about 5.5 KB more). The
extra requests mostly offset upload savings at these rates. On the constrained
profile, unchanged/body medians improve by only 0.18/0.37 seconds; on the faster
profile they regress by 0.10/0.27 seconds. Package-upgrade traffic is unchanged,
and its time regresses slightly. This is a bandwidth improvement, not a major
wall-clock speedup. Further work should reduce round trips and avoid downloading
components already available as verifiable local inputs.

All 36 network consumers (18 per version) passed their expected compile counts,
current-runtime checks, and actual tests. Nine initial v3 control cases passed
before the SDK-evidence extraction; the final evidence path additionally passed
roundtrip/corruption unit tests and all 18 v3 network consumers. The unit suite
passes 118 tests. No GitHub CI was run; these results do not establish remote
host or platform portability.


The final package-free regression passed all four 10-project cases at 10 ms
request delay: unchanged compiled 0 projects (10 hits), leaf/shared body edits
compiled 1 project (9 hits), and an empty cache compiled all 10. Every case
matched raw MSBuild runtime and reference-assembly bytes and the executable
output oracle. End-to-end times were 7.11, 7.70, 7.57, and 11.29 seconds,
respectively; this small graph still carries orchestration overhead relative to
raw MSBuild (3.57–3.67 seconds).

Related native-cache, MSBuild-tool, package-staging, and analyzer-package suites
passed another 33 tests (151 unit/regression tests total).
