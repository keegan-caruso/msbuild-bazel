# dotnet/runtime qualification

Recorded graph baseline: runtime v10.0.0
`60629d14374c56f1cb51819049ad1fa529307f8d`, SDK 10.0.400, Linux ARM64,
four CPU / 8 GiB, four MSBuild nodes. The original reports and commands are at
[the pre-cutover revision](history.md); helper locations below reflect the graph-only tree.

## Scope and results

| Control | Measured result |
| --- | --- |
| Expanded graph | 260 paths / 543 configurations / 481 compilations / 39 roots |
| Complete-source raw parity | All 3,622 compared compiled DLL/PDB/resource files match |
| Snapshot recovery | All 10,780 files match bytes and modes |
| Eight upstream suites | 118,952 passed / 64 skipped / zero failed; 119,016 normalized outcomes |
| Execution host | 123 managed / eight native source producers; private net8 Formatters included |
| Bazel baselines | 8.8 and 9.2 seed/replay/body/API/failure/recovery controls |
| Independent recovery | Stopped 8.8 producer; relocated 9.2 consumer; exact outputs and current loaded hashes |

Native producers preserve upstream CMake/Ninja and declared toolchain/source archives.
Source-only host composition includes CoreLib, CoreCLR, JIT, host and required support
libraries. Ordinary app and reviewed upstream executable tests run with the SDK absent
from their execution namespace. Loaded-component hashes tie execution to current source
producers; no installed framework payload supplies missing binaries.

## Invalidation and fault controls

Managed edits cover shared padding (119 misses / 16 raw Csc), resource (1/1),
DiagnosticSource template (111/8), and private URI props (249/14). Reverting the
private props restored 249 snapshots although preparation payload bytes matched;
that Restore invalidation remains an optimization question.

Bounded native source/header/compiler edits rerun one native action and no graph or
Restore action; the other four producers remain unchanged. Reversions restore native
bytes from cache. All eight suites retain matching outcomes.

Missing snapshots/artifacts become misses (480/1 and 478/3 hits/misses) and repair.
Corrupt pointers/blobs fail explicitly. A 503 control fails after bounded retries
(33 rejected requests); healthy recovery returns 481/0 without partial entries.
The fault proxy does not change backend selection. Concurrent divergent remote
writers are detected only for entries observed before publication; HTTP has no
atomic compare-and-swap guarantee.

## Preparation and checks

The source/package archive identities and reviewed slices are in the driver and
`tests/runtime/subset_slices.json`. Preparation uses owned disposable workspaces,
explicit offline packages and reviewed document/input/output translations. Begin
with a small slice and add selections without flattening authored frameworks:

```sh
python3 tests/graph_build/upstream/runtime_prepare.py --help
python3 tests/runtime/native_prepare.py --help
python3 tests/runtime/native_component_prepare.py --help
python3 tests/graph_build/upstream/runtime_application.py --help
python3 tests/graph_build/upstream/runtime_suite.py --help
python3 tests/graph_build/upstream/runtime_full_source.py --help
python3 tests/graph_build/upstream/runtime_remote.py --help
python3 tests/graph_build/upstream/runtime_cache_faults.py --help
```

Use the [qualified Linux environment](linux-workers.md), a stopped independent
producer and fresh consumer paths for recovery. Save reports outside Git; summarize
versions, exact scope, outcomes, bytes/modes, loaded hashes, failure recovery and
measurement boundaries. [Performance](performance.md) is the single timing scorecard.

## Limits

This is a reviewed selected graph, not the whole runtime repository or a universal
upstream translator. Native producers are shared with the raw managed comparison;
there is no independent native scheduling parity claim. Full source SDK, NativeAOT,
RBE and x86-64 qualification are separate. The cutover ports artifact utilities and
entrypoints; it has not repeated this full upstream series.
