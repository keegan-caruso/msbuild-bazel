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
records, payload, restore data and binding index. These are component samples;
full Orchard workflow qualification follows.

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

## Validation so far

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

One optimized discovery preflight failed due to scratch-disk exhaustion and is
not counted as a performance result. Completed benchmark data was archived and
verified before reclaiming disk space; the package-copy removal also lowers the
owned discovery scratch requirement. No CI, push or merge was performed.
