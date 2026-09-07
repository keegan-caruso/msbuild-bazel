# Generated graph cache acceptance: milestone 3

Status: the package-free R01 and managed-package R02 cache probes are
implemented in `tools/probe_graph_cache.py`. The scoped suite remains in
`tests/graph_cache`; `tests/graph_cache_full` adds the package and failure
controls while inheriting every R01 assertion. See [package-free findings](graph-cache-findings.md)
and [managed-package cache findings](graph-package-cache-findings.md) for
measured evidence and remaining gates. Full cache acceptance does not by itself
establish every R02 PrivateAssets or broader NuGet scenario.

## Boundary and prerequisite

Use the milestone 1 configured-node identities and normalized input declarations
from [graph-export-contract.md](graph-export-contract.md). Milestone 2 provides
`tools/prepare_graph.py --workspace RESTORED --manifest GRAPH.json --output BAZELDIR`
and generated `:node_<id>` targets plus `:all`. These are the agreed integration
points with the concurrent execution track; implementation evidence belongs to
that track. The suite exercises the generated adapter while keeping its assertions independent.

Keep SDK-style MSBuild compilation, strict dependency-result replay, native local
sandbox execution and local disk caching. Restore and package acquisition happen
in preparation. One project path plus global properties identifies one configured
node; source hashes affect action identity without changing node identity. This
fixture uses Release/net10.0 and one compatible host identity. No remote-cache,
remote-execution, general NuGet or cross-platform claim follows.

Use a fresh copy of the exporter test's diamond: Shared supplies `shared-v1`;
Left and Right append `:left` and `:right`; App prints the two joined by `|`.
Instrument compile logs with exactly one `SPIKE_COMPILE:<relative-csproj-path>`
line per real compilation. Never build the checked-in fixture. Baseline output
must come from an ordinary MSBuild static-graph build in a separate copy.

## Independent mutation matrix

Each mutation starts from an independently warmed baseline, so earlier changes
cannot explain a later action set. Preserve the same host/toolchain/policy.
Choose observable source changes that change consumer bundle bytes; this avoids
confusing Bazel's valid unchanged-output pruning with invalidation failures.
Global graph JSON must not become an input to every node action: project actions
consume their own input slices and direct dependency bundles.

| Case | Change from its baseline | Actions that execute | Observable output |
| --- | --- | --- | --- |
| `cold` | Empty disk cache/output base | Shared, Left, Right, App | `shared-v1:left\|shared-v1:right` |
| `unchanged` | None | None | Baseline |
| `appEdit` | App source appends marker | App | Baseline plus `\|app-v2` |
| `leftEdit` | Left source changes suffix | Left, App | `shared-v1:left-v2\|shared-v1:right` |
| `sharedEdit` | Shared source changes value | All four | `shared-v2:left\|shared-v2:right` |
| `importEdit` | Shared Directory.Build import changes declared compiler input; App prints marker | All four | Baseline plus `\|config-v2` |
| `packageCold` | Separate pinned managed-package fixture, package only consumed by Left | All four | `shared-v1:left/package-v1\|shared-v1:right` |
| `packageUpgrade` | Upgrade Left package from v1 to v2, restore and re-export | Left, App | `shared-v1:left/package-v2\|shared-v1:right` |
| `graphEdgeAdded` | Add Right -> Left and update Right source to call Left | Right, App | `shared-v1:left\|shared-v1:right+shared-v1:left` |
| `diskCache` | Remove workspace build outputs and Bazel output base, retain disk cache | None; four disk-cache hits | Baseline |
| `packageDiskCache` | Fresh package preparation after deleting the output base | None; four disk-cache hits | Package v1 baseline |
| `packageRelocated` | Fresh package consumer after deleting producer and output base | None; four disk-cache hits | Package v1 baseline |
| `relocated` | Fresh restored consumer at different path, delete producer and use fresh output base | None; four disk-cache hits | Baseline |

The package case uses its own `packageCold` baseline and checksum-pinned package
versions, without network access in compilation. Preserve both restored manifests
and verified payload hashes. Removing preparation files must not break execution.
For the edge addition, Shared and Left keep their configured IDs and action
inputs. Re-export and regenerate before Bazel analysis; retain the old and new
manifests plus Bazel dependency-analysis evidence. Do not hand-edit generated
BUILD files to obtain the expected edge.

For cache recovery, retain only the local disk cache, declared toolchain inputs
and restored source inputs. No reused output base, bin/obj compilation products,
producer bundles or producer checkout may supply the recovered outputs. Restore
metadata under obj may be recreated in preparation. Hash all consumer bundle
files and executable bits and compare against cold output; exclude diagnostics
from bundles. Run the recovered App. A warm no-op build is insufficient evidence.

## Failure controls

Each failure starts independently from a valid export, is attempted with a warm
cache, and must fail before compilation or publication of a replacement plan:

| Case | Perturbation | Diagnostic |
| --- | --- | --- |
| `missingSource` | Delete a manifest-declared source | `missing-input` |
| `missingPackage` | Delete a declared package payload | `missing-input` |
| `corruptPackage` | Change payload bytes without updating the declared hash | `hash-mismatch` |
| `staleManifest` | Edit project reference structure, then submit the old graph manifest | `stale-manifest` |
| `staleRestore` | Upgrade PackageReference while retaining the previous restore metadata | `stale-restore` |

A corrupt-input test must preserve the old manifest; re-exporting the corrupt
bytes would test different behavior. An intentional upgrade restores and exports
new inputs; stale data must never silently fall back to the old cached plan.
These codes are adapter-facing preparation diagnostics; the tests preserve the
actual failure log and parse the reported code, rather than assigning an expected
code to an arbitrary failure.

## Probe/report contract

Run the package-free R01 probe and focused suite as:

```sh
python3 tools/probe_graph_cache.py --package-free --output artifacts/graph-cache-probe
python3 -m unittest discover -s tests/graph_cache -v
```

`--output` must not exist. The probe retains reports, raw logs and bundle evidence
under that directory, returns nonzero on setup or unexpected build failure, and
writes `report.json` only after collecting all cases. Expected negative cases
have their own nonzero result while a complete probe returns zero. Tooling,
network or sandbox failures must be errors rather than skips. The acceptance
suite retains its temporary evidence directory and prints its location.

Run the full package cache contract with:

```sh
python3 tools/probe_graph_cache.py --output artifacts/graph-package-cache-probe
python3 -m unittest discover -s tests/graph_cache_full -v
```

The R01 report identifies itself with `scope: "R01-package-free-cache"` and
`pendingTracks`; it does not emit package or failure-case results. Full reports
identify themselves with `scope: "R02-managed-package-cache"`. The runner now
emits workspace-relative project paths in compile markers, while the existing
action report's `compiledProjects` retains project stems for compatibility.

The full report schema version 1 has `schemaVersion`, `baselineOutput`, `cases`,
`packageUpgrade`, `graphEdgeAdded`, and `failures`. Project strings are normalized
workspace-relative csproj paths (`src/Left/Left.csproj`), not display names.
Each case has:

- `returncode`, `applicationReturncode`, `applicationOutput`.
- `executedProjects` and `cacheHitProjects`, derived from Bazel execution evidence.
  An unchanged in-memory reuse may have neither new executions nor disk hits.
- `executionLog`, a report-relative raw Bazel execution log; `executions`, one
  record per executed/cache-hit configured action with `nodeId`, `project`,
  `cacheHit`, `runner`, `remotable`, `remoteCacheable`, and `log` for real actions.
  Real-action logs contain the compile marker described above. Dependency replay
  must not cause extra compile markers inside consumers.
- `bundleFiles`, keyed by stable logical bundle path across all four nodes. Each
  value has `file` (report-relative retained bytes), `sha256`, and `executable`.
  `bundleDigest` is SHA-256 of UTF-8 JSON mapping those same logical paths to
  `{sha256, executable}` values, with sorted keys and separators `(',', ':')`.
  The suite recomputes file hashes, permission flags and the combined digest.
- Recovery cases additionally have `outputsAbsentBeforeBuild` and
  `outputBaseAbsentBeforeBuild`; relocation also has `producerWorkspaceAbsent`,
  `producerWorkspace` and `consumerWorkspace`. Record deletion and absence checks
  immediately before execution, not after the probe removes evidence.

`packageUpgrade` records `beforeVersion`, `afterVersion`,
`beforePayloadSha256`, `afterPayloadSha256` and `preparationWorkspaceAbsent`.
`graphEdgeAdded` records report-relative `beforeManifest`, `afterManifest`,
`analysisLog`, `analyzedDependencies` (node ID to sorted direct dependency IDs),
and monotonic `planGenerationSequence`/`analysisSequence`. Analysis dependencies
must be obtained from Bazel, not copied from the expected manifest.
Each `failures` entry has `returncode`, `diagnostic`, `executedProjects`,
`publishedPlan` (false), and a report-relative `log` containing the diagnostic.

The report is evidence produced by a real probe, never a fixture response or
replacement for running builds. Review retained raw logs when implementing the
probe; the Python assertions alone cannot authenticate self-reported filesystem
absence or sequence numbers. Existing e2e and graph export suites remain
unaffected because these tests live in their own discovery directory.

## First red result

On 2026-09-06, in `/private/tmp/msbuild-graph-cache-contract` on macOS, ran:

```text
python3 -m unittest discover -s tests/graph_cache -v
setUpClass (test_graph_cache.GraphCacheAcceptance) ... ERROR
AssertionError: Milestone 3 cache probe is not implemented: tools/probe_graph_cache.py
Ran 0 tests in 0.000s
FAILED (errors=1)
```

Exit status was 1. The ten test methods are present but the missing capability
fails class setup; no acceptance scenarios executed and none were skipped.
This is the expected pre-implementation red result, not a passing milestone.
Linux validation and real probe measurements remain required after implementation.
