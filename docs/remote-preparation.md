# Remote preparation snapshots

[NuGet cache reuse and split package objects](nuget-cache-reuse.md) extend this
workflow with transfer policy v2. The measurements below describe the original
v1 full-payload transport. [Preparation components v3](preparation-components.md)
further split sources, metadata, and SDK evidence and measure shaped networks.

The native workflow can consume and publish an explicit immutable HTTP snapshot
containing both the project-cache catalog and a qualified preparation artifact.
A fresh worker can skip EvaluationProbe, GraphExport, package extraction and
native-plan materialization after proving its current inputs equivalent. Existing
C# content edits retain discovery and package results, updating source identities.
API edits still invalidate downstream compilation through reference assemblies.

## Command

Run in the pinned Nix shell with restored inputs and prebuilt controller tools:

```sh
python3 tools/native_workflow.py \
  --workspace /absolute/restored/source --state /absolute/owned/state \
  --entry path/App.csproj --output /absolute/new/report \
  --trust-system-nix-store \
  --remote-endpoint https://trusted-cache.example/native \
  --remote-snapshot SHA256
```

Omit `--remote-snapshot` for an empty-cache build that publishes the first snapshot.
The endpoint option enables leased preparation reuse and guarded source refresh.
`report.json` returns `remote.publishedSnapshot` after successful consumption and
final integrity checks. The caller pins that digest on the next worker; there is
no implicit latest pointer. The service accepts GET/PUT `/cas/<sha256>`. This is
the native broker protocol, not Bazel's Action Cache or remote execution API.
The endpoint and snapshot publisher are trusted build inputs. CAS hashes detect
corruption; they do not authenticate an unknown producer.

Missing, corrupt or incompatible preparation falls back to fresh discovery.
Missing/corrupt compiled bundles rebuild the affected projects. A failed build,
test or final lease check publishes no remote snapshot. Publication transport
failure leaves a successful local build usable, with `remote.publicationError`
and no new snapshot digest. Orphan blobs from an interrupted upload are harmless.

## Relocation proof and limits

The portable request retains entries, properties, controller bytes, native toolchain,
Python, SDK, discovery/source/store policies and all tool-tree contents. Tool roles
replace controller installation paths only; independently built tool trees with
changed content still miss. Consumer source and discovery tools are sealed before
checking the candidate. Current path-bound request/environment identities are
reconstructed and checked against the selected discovery contract.

Only known restore metadata paths are normalized. The restore receipt's
`dgSpecHash` uses the existing graph normalization; success and every other field
remain checked. Assets, dependency specs, generated props/targets, packages,
namespace, modes and other source bytes remain verified. No blanket removal of
absolute paths or restore state is allowed. Changes outside admitted existing C#
compile inputs force fresh discovery.

The first slice requires the same workspace nesting depth, SDK/runtime paths,
OS/platform/build, architecture and CPU count. Boot session may differ. Recorded
ancestor absences are relocated and rechecked; an appearing external input cannot
be accepted. Full source/tool checks remain held through consumption. A downloaded
certificate is never itself a lease.

The preparation ZIP preserves directories and modes, rejects unsafe paths,
symlinks and duplicate names, and bounds compressed/expanded size and member count.
The original v1 artifact contained the complete prepared payload, including
packages. Its package duplication is addressed by the v2 extension linked above.
Neither measurement claims bandwidth-efficient WAN operation. Different-depth workers,
arbitrary MSBuild logic and general platforms remain outside qualification.

## Validation and measurements

The focused unit suite covers path/receipt relocation, changed sources, changed
assets and namespace, ancestor emergence, host/invocation mismatch, archive
corruption, and pinned snapshot validation. The real Serilog probe deletes the
producer and creates fresh source/state/Bazel roots for each consumer:

```sh
python3 tests/preparation_reuse/probe_remote_preparation.py \
  --checkout /path/to/pinned/serilog --packages /path/to/packages \
  --output /absolute/new/probe
python3 tests/preparation_reuse/measure_remote_preparation.py \
  --output /absolute/new/measurement --count 100 --repetitions 3 --delay-ms 10
```

Measurements include preparation, full input validation, remote transfer,
Bazel startup/build and publication. Both paths exclude Restore and SDK/package
acquisition. Raw MSBuild starts without compiler outputs. Each measured consumer
has new state and a fresh protected-store session. The producer is deleted first;
the server resets to the producer's immutable snapshot for every case. Runtime
bytes, reference assemblies, precise compile misses and executable results are
checked against raw MSBuild. This is same-host loopback HTTP with 10 ms per request,
not independent machines, a constrained-bandwidth network, or a WAN.

### Accepted correctness run

Pinned Serilog revision `49b5339ce85385dc52d4d8e8f2b8308becf23506`,
SDK 10.0.400, native macOS ARM64 sandbox:

| Fresh consumer | Compiles | Discovery | Outcome |
|---|---:|---|---|
| Unchanged | 0 | Reused | Test passes |
| Existing method body | 1 | Reused | Test passes with current runtime |
| Public API addition | 2 | Reused | Both projects rebuild |
| New source file | 2 | Fresh | Test passes |
| PolySharp 1.15.0 to 1.16.0 | 2 | Fresh fallback | Test passes; no portable preparation published |
| Corrupt preparation blob | 0 | Fresh | Compiled project bundles remain usable |
| Missing snapshot | 2 | Fresh | Rebuild and publish |
| Corrupt project bundle | 1 | Reused | Affected project repaired |
| Failed approval test | 0 | Fresh | No local build pointer or remote PUT |
| Compiler error | 1 | Reused | Returns failure; no publication |
| Source changes during accepted lease | 0 | Reused initially | Final check rejects; no publication |

Two failure-path fixes accompany this work. Native fresh fallback uses prebuilt
GraphExport rather than mutating its already-bound controller identity. The native
build subprocess disables .NET diagnostics and cleans scratch state on failure;
otherwise leftover diagnostic FIFOs can stall Bazel execution-log hashing. The
compiler-error control verifies the failure returns normally.

Validation: 96 preparation tests, 23 native-cache tests, and the .NET build/style
checks pass. No GitHub CI was run.

### Accepted 100-project measurements

September 17, 2026; three runs per case, 10 ms per HTTP request, serial
measurements with alternating raw/native order. All 12 consumers passed exact
runtime-byte, 100-reference-assembly, compile-set and executable-output checks.

| Fresh 100-project consumer | Native median | Raw MSBuild median | Compiles / hits |
|---|---:|---:|---:|
| Unchanged | 11.24 s | 26.10 s | 0 / 100 |
| Leaf body edit | 12.27 s | 26.24 s | 1 / 99 |
| Shared-root body edit | 11.98 s | 25.99 s | 1 / 99 |
| Empty remote cache | 45.75 s | 26.08 s | 100 / 0 |

Against the previous API/runtime implementation's fresh-consumer medians, the
leaf case improved from 21.98 to 12.27 seconds (44.2% less time), and the shared
case from 22.14 to 11.98 seconds (45.9% less time). Both still compile exactly one
project. Preparation medians dropped from about 12.2 seconds to 1.99/1.98 seconds.
Bazel startup plus execution now dominates cached runs at 6.57–7.40 seconds.

The empty-cache guardrail is **not yet at the desired target**: 45.75 seconds is
75.4% slower than raw's 26.08 seconds. Its preparation median is 12.20 seconds
and Bazel plus compilation is 31.80 seconds. Cold discovery/preparation remains
a separate optimization; the remote hit gain does not remove it.

The synthetic cached consumers download 7.15–7.21 MB and upload 1.49–1.54 MB.
Compared with the previous compiled-bundle-only snapshot, the added preparation
artifact saves CPU work but increases transfer. The package-heavy Serilog
unchanged control downloads 49.57 MB and uploads 46.18 MB, including a roughly
46 MB prepared payload. Deduplicating package payloads and reconstructing them
from already-verified restored inputs is still needed before claiming good WAN
performance. These loopback measurements do not include bandwidth constraints.

The new benchmark omits `synthetic.json`, which is harness-only oracle metadata
that changes along with a body edit. Keeping it in the source domain correctly
forces fresh discovery, so removing it makes the intended compile-only case
explicit rather than weakening production namespace validation.

Evidence: `/private/tmp/mrp-100/report.json` (12 accepted timing cases),
`/private/tmp/mrp-real3/report.json` (11 accepted real-project controls).
