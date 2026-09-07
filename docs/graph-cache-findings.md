# R01 package-free generated-graph cache

The package-free probe exercises the exported Release/net10.0 diamond through
native Bazel actions and a local disk cache. It retains an ordinary MSBuild
graph-build oracle in a separate copy, raw execution logs, generated manifests,
Bazel query evidence and complete consumer-bundle bytes with executable flags.
The report is explicitly scoped `R01-package-free-cache`; it is not the full
historical milestone 3 report.

## Experiment

```sh
python3 -m unittest discover -s tests/graph_cache -v
# Or retain evidence at a chosen new path:
python3 tools/probe_graph_cache.py --output artifacts/graph-cache-probe
```

Each source/import/edge mutation regenerates and warms the original fixture
before changing one input. Preparation restores and exports the graph again,
then replaces the generated Bazel workspace. The global graph manifest is not
injected into each action. The edge case queries the actual generated Bazel rule
attributes after generation and preserves both manifests and raw XML output.

Recovery deletes the output base and generated workspace, regenerates from
restored sources without compilation products and retains the disk cache.
Relocation additionally deletes both producer source and generated workspaces,
restores a fresh copy at a different path, generates the consumer and deletes its
preparation workspace before building. The probe records absence immediately
before each build. Retained evidence copies are outside generated action inputs;
they are available for audit, never used as a restore source.

The suite recomputes every retained file hash and executable bit, compares
combined bundle digests for cold/recovery/relocation and executes each built App.
Each real action must have exactly one compile marker for its own project and
must report the native sandbox runner with remote execution/cache disabled.
The existing runner emits unique diamond project stems rather than paths in
compile markers; report project paths come from the exported configured-node
mapping. This preserves the runner's existing validation contract.

## Validation record

Native macOS ARM64 validation on 2026-09-06 uses .NET SDK 10.0.100 and Nix Bazel 8.4.2.
The first run stopped before graph-edge execution because the harness combined
Bazel query stderr diagnostics with XML stdout. Separating stdout for parsing
and retaining both streams in the raw log fixes that harness error. A second
run reached recovery but exposed Bazel read-only output directories; recovery
now makes real directories writable without following toolchain symlinks before
deleting the output base.

The third run retained evidence at
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/msbuild-graph-cache-qal_cq7_/probe`.
It ran eight tests: six passed and two failed. The observed matrix was:

| Case | Executed projects | Disk hits | Application |
| --- | --- | --- | --- |
| cold | all four | 0 | baseline |
| unchanged | none | 0 | baseline |
| App edit | App | 0 | baseline plus `|app-v2` |
| Left edit | Left, App | 0 | `shared-v1:left-v2|shared-v1:right` |
| Shared edit | all four | 0 | `shared-v2:left|shared-v2:right` |
| shared import edit | all four | 0 | baseline plus `|config-v2` |
| added Right to Left edge | Right, App | 0 | `shared-v1:left|shared-v1:right+shared-v1:left` |
| deleted output-base recovery | none | 4 | baseline |
| relocated recovery | all four | 0 | baseline |

Baseline was `shared-v1:left|shared-v1:right`. Real executions used
`darwin-sandbox` with remote execution and caching disabled.

Recovery's bundle comparison failed because Bazel downloaded only the top-level
App bundle, despite reporting all four disk hits. The probe now explicitly uses
`--remote_download_outputs=all` and rejects missing configured bundles.
Relocation's expected zero-execution assertion failed: the Shared action's only
changed input was `restore/10ea6eaa781e181c07593118.json`. Preparation serialized
NuGet's path-derived `dgSpecHash` into action inputs. Its normalization is a shared
preparation fix owned by the handoff track and requires integrated validation.
The new independent ordinary Shared-edit oracle, full-download flag and stronger
bundle-presence assertion were added after this run and also await that validation.
The R01 cache acceptance gate is therefore still open at this checkpoint.

## Remaining gates

R01 handoff/discovery controls are a separate track; their acceptance is not
claimed by this cache report. R02 package cold/upgrade, missing/corrupt package
and stale-restore cases remain pending. The original full assertions are
preserved under `tests/graph_cache_full`; run that directory separately as the
future full milestone 3 gate. Its package/path-marker/failure requirements are
not silently removed by the passing package-free scope.

Linux validation must run the same focused suite through CI. No remote cache,
remote execution, cross-platform reuse, arbitrary configuration/package support
or complete host runtime closure follows. Concurrent native runs establish
correctness only; no performance measurements are reported.

## Integrated native macOS acceptance

After integrating handoff normalization and complete output download, ran
`python3 -m unittest discover -s tests/graph_cache -v` on macOS ARM64 with the
pinned Nix tools at integration source `c8e19ff` (unchanged production source
during the run). All **8 tests passed** in 125.658 seconds. Evidence:
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/msbuild-graph-cache-uw3b8wik/probe`.
Both clean recovery and deleted-producer relocation record four disk-cache hits,
no project executions, identical bundle hashes/permissions and correct App output.
The Shared edit also matches a separately rebuilt ordinary MSBuild baseline.
This supersedes the partial six-of-eight result above; Linux at the combined
revision remains a separate gate.
