# Spike interfaces (v1)

This implemented v1 contract was written before the driver. It remains the
same-path MSBuild control. The separate [replay contract](replay-interface.md)
and [Bazel contract](bazel-interface.md) describe the later implemented boundaries.

## First milestone: process interface

`python3 tools/spike.py --request /absolute/request.json`

A request is a JSON object with these fields:

| Field | Meaning |
| --- | --- |
| `schemaVersion` | Integer `1` |
| `operation` | `restore`, `baseline`, or `project` |
| `workspace` | Absolute path to an isolated fixture checkout; never the source fixture itself |
| `output` | Absolute path to a new action-output directory outside the workspace |
| `configuration` | `Release` for the first milestone |
| `project` | For project actions only: `Shared` or `App` |
| `dependencies` | For project actions: array of completed action-output directories; empty for Shared, one Shared output for App |

`workspace` contains the fixture's project files, version pin, traversal entry point and build instrumentation. Restore is explicit and separate from compilation. A project action uses `-isolateProjects`, consumes dependency results caches and writes its own result cache. It must not run restore or recursively compile Shared during an App action. Normal baseline compilation uses the traversal graph.

Success exits zero and writes `result.json` and `build.log` under `output`. Failure exits nonzero and produces a useful diagnostic; partial outputs must never be treated as a usable dependency.

A completed project action additionally exports:

- `results.cache`: MSBuild result metadata (opaque; not rewritten).
- `artifacts/`: project bin/obj files preserving workspace-relative paths for this first milestone. The conservative set is intentional until the consumed files are measured.
- `result.json`: `schemaVersion`, `operation`, `project`, `workspace`, `configuration`, `targetFramework`, `sdkVersion`, `artifacts` (relative file list), and `resultsCache`.

The consumer checks the dependency identity, configuration, SDK, framework, workspace path and listed artifact existence before invoking MSBuild. It stages dependency artifacts back into their expected paths. The initial implementation supports the SAME absolute workspace path only. A changed path must fail explicitly, not fall back to rebuilding. Export and rehydrate after deleting bin/obj proves artifact handoff without claiming cache relocation.

## Evidence

Tests inspect MSBuild's `SPIKE_COMPILE:<project>` messages emitted immediately before CoreCompile and execute the built App DLL independently. The driver cannot supply its own list of compiled projects as evidence. Positive handoff tests also remove both projects' bin/obj trees, then restore only consumer restore metadata plus the declared dependency artifact bundle.

## Later implemented boundaries

The [raw path probe](path-findings.md) measured that changing only the bundle
directory succeeds, but changing the absolute workspace path fails MSBuild's
configured-project cache lookup. This v1 interface retains its same-workspace
restriction; the probe bypasses that guard for investigation only.

The separate [public-API replay interface](replay-interface.md) uses normalized
project identity, target-result metadata and staged artifacts. It supports
relocation for the fixture and rejects missing results without falling back to
dependency compilation. See [replay findings](replay-findings.md). It does not
change the v1 request or bundle format.

The implemented [two-target Bazel contract](bazel-interface.md) maps Shared and
App to separate actions with declared inputs and output bundles. Execution logs
verify scheduling and local disk-cache reuse; see [Bazel findings](bazel-findings.md).

General graph export remains deferred. A future exporter must use MSBuild
ProjectGraph and preserve global properties rather than infer arbitrary csproj
semantics from XML. See the [current plan](spike-plan.md) for remaining work.
