# Discovery and binding profiling

The 202-project Orchard resource edit spent 329–333 seconds in discovery and ran
202 binding actions, although only four projects compiled. Profiling isolates
work inside the components from Bazel scheduling and end-to-end workflow cost.

## Measured component changes

| Operation | Before | After |
| --- | ---: | ---: |
| Discovery | 337.551 s | 160.143 s |
| Representative small-project binding | 1.018–1.221 s | 0.056–0.085 s |
| CMS host binding | 3.498 s | 0.375 s |

Discovery first fell to 213.451 seconds after unique-file hash reuse and removal
of redundant package materialization, then to 160.143 seconds after verified
same-action graph reuse. All five metadata comparisons passed: graph, identity
records, payload, restore data and binding index. These are component samples; the full workflow results below separately
include Bazel scheduling, compilation, runtime composition and cache publication.

The original graph has 212,715 input references but 20,716 unique paths. Export,
input validation and native plan construction now hash unique files within each
pass. Raw and normalized views remain distinct, every expected digest is checked,
and final input verification remains. Export also checks file stamps before
reusing a digest. No digest cache persists across invocations.

The Bazel-owned path now reuses the graph captured by the same discovery instance
only after rechecking its entire read closure and external absent paths. It keeps
an isolated graph copy. Ordinary preparation of externally supplied graphs still
re-exports and compares them. Controls reject reuse without capture, changed
source bytes with restored timestamps, added source files, changed tool inputs,
and newly appearing external paths; caller mutation cannot alter the captured
copy. Final verification after consumption remains enforced.

When Bazel supplies extracted package directories, intermediate preparation
writes package metadata without another extraction/copy into a throwaway tree.
The native plan verifies the declared staged contents and records exactly the
same payload entries. Archive and package-policy verification remain intact.
The legacy repository-extraction path keeps its previous materialization.

## Bazel-owned project boundaries

Discovery declares one template directory per selected project. Each contains
only its closure manifest, required payload map and source-dependent records.
Bazel bindings consume their own template and source bodies, plus the required
layout-validation marker. Unchanged templates can therefore preserve binding
cache hits after another project's resource edit. Legacy shared discovery plans
remain supported.

Generating all 202 templates took 3.732 seconds once in the component probe.
Bindings no longer repeatedly delete irrelevant entries from a global JSON map,
nor reread and hash every unchanged dependency record. Linked sources and global
source roles preserve legacy behavior; all four bound-plan files match byte for
byte in representative Orchard and synthetic controls.

## Full Orchard qualification

The same pinned 202-project Orchard Release/Production graph was run on one
macOS ARM64 host with a loopback HTTP cache and a shared pinned archive repository
cache. The comparison uses the previous combined package qualification, not a
new raw-MSBuild measurement. Each producer/edit/recovery result is one sample;
no-op values are medians of three runs.

| Workflow | Previous | Current |
| --- | ---: | ---: |
| Producer, 202 compiles / 287 package extractions | 1,120.087 s | 831.542 s |
| Stylesheet edit, four compiles | 687.674 s | 338.668 s |
| Discovery within stylesheet edit | 329.407 s | 150.306 s |
| Binding actions on stylesheet edit | 202 | 4 |
| Producer-deleted fresh remote recovery | 36.825 s | 35.923 s |
| No-op median | 6.489 s | 6.441 s |

The stylesheet edit is **50.8% faster (2.03x)**. Discovery is 54.4% faster in
that workflow. Binding and compilation execute only for OrchardCore.Setup,
OrchardCore.Application.Cms.Core.Targets, OrchardCore.Application.Cms.Targets
and OrchardCore.Cms.Web. All 198 other bindings remain locally reusable.

The producer publishes 17,128 objects / 2,756,332,356 bytes. The edit publishes
5,583 objects / 1,296,437,103 bytes. Both report zero publication failures.
The new templates add cache metadata: upload bytes increase slightly versus the
previous implementation, despite substantially lower execution time.

After deleting the producer Bazel output and generated workspace trees, fresh
recovery hits all 202 binding actions, 202 compile actions, 287 package extraction
actions, discovery, restore and runtime composition. It performs zero compilation
and downloads zero extracted package files. All **3,457 application files** match
byte for byte. HTTP 200, C# headers, Razor markers and the changed stylesheet pass;
the recovered application also runs with both source checkouts unavailable.
The three no-ops execute no discovery, binding, compilation or extraction.

The remaining single graph export costs 74.013 seconds in the producer and is
still a substantial discovery cost. Resource edits still rerun whole-graph
discovery; this change makes it cheaper and lets Bazel preserve downstream
project reuse. Host compilation, runtime composition and publication also remain
in the edit path. This is not raw-MSBuild parity, WAN-cache qualification or
remote-execution qualification. C#/Razor/generator edits were not rebenchmarked
on the full graph in this pass; small native source/import/resource controls and
the previous full-graph package qualification provide adjacent coverage.

Machine-readable counts, phase timings, exact changed project paths, snapshot
controls and previous comparison samples are in
[discovery-binding-evidence.json](discovery-binding-evidence.json).

## Validation

- Full local suite: 62 workflow tests, one Linux-only skip, 33 preparation tests,
  five style tests, warning-free builds and Starlark formatting checks.
- Native four-project graph: resource/local-import edits each bind and compile
  two projects; shared import binds/compiles four; no-op performs neither.
- Real-package probe: legacy/action-produced DLL/PDB parity, producer-deleted
  remote recovery with zero compilation or extracted-file download, followed by
  a one-project source edit that downloads no unrelated sibling package files.
- Captured-graph mutation and isolated-copy controls all pass.

Native acceptance also exposed an empty-package repository glob regression from
the earlier archive export change. The glob now explicitly permits an empty
package set, with an actual Bazel query regression test.

One optimized component preflight and the first full producer failed due to
scratch-disk exhaustion and are excluded from timings. The producer failure
occurred during compilation and execution-report writing. Completed metadata
and traces were compressed and verified; retired generated build trees were
removed while retaining their reports/profiles. The full producer was then
restarted from clean generated state with 8.2 GiB free. No cleanup ran during
the accepted producer or stylesheet timing. No CI, push or merge was performed.

## Reproduction and retained evidence

Use the owned-workflow build request described in the
[combined qualification](orchard-package-qualification.md), with the same pinned
SDK/Bazel, Orchard revision, project layout, locked restore, project actions,
package actions, direct checkout and remote cache. Enable `RULES_MSBUILD_TRACE=1`
to retain discovery phase timings. Run a producer with upload enabled, append a
CSS marker to Setup's `wwwroot/Styles/setup.min.css`, and rebuild. Shut down Bazel,
remove producer output/generated trees, and recover at a different checkout and
state path with uploads disabled; then run three no-ops.

The local evidence directory is `/private/tmp/orchard-binding-benchmark`, with
accepted reports, execution records, Bazel profiles, discovery phase reports,
application hashes and runtime logs. The producer request and exact harness are
retained under `/private/tmp/orchard-pilot-evidence/` as
`binding-producer-request.json` and `run_binding_benchmark.py`.

Implementation validation ran `nix develop -c bash scripts/check-dotnet.sh`
and these native probe entrypoints with isolated output directories:

- `tests/remote_workers/discovery_snapshot_probe.py`
- `tests/remote_workers/project_input_probe.py`
- `tests/remote_workers/package_action_probe.py`

Each probe's `--help` lists its arguments. Their accepted local reports are
included in the evidence file.
