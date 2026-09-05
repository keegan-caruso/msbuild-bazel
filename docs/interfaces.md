# Spike interfaces (v1)

This contract is written before the adapter implementation. The first executable milestone proves the MSBuild action boundary. A Bazel rule consumes the same project boundary only after that proof passes.

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

## Next milestone: Bazel rule boundary (proposed, not implemented)

`msbuild_project(project, properties, sources, imports, restore_assets, toolchain, deps)`

Inputs include all configured-project inputs and the dependency output bundles. Outputs are a declared artifact tree, result metadata and diagnostic logs. Each configured project maps to one action with mnemonic `MSBuildProject`.

A graph exporter must emit this graph before Bazel analysis. It must use MSBuild ProjectGraph and preserve global properties; it must not infer arbitrary csproj semantics from XML alone.

Bazel execution logs, not elapsed time, will prove unchanged/App-only/Shared-change action reuse. The rule must solve stable paths and toolchain declaration before remote-cache or sandbox portability claims.
