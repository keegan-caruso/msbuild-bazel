# Explicit MSBuild tool inputs

GraphExport and ReplayPlugin now accept their build framework and reference
engine as separate inputs. They do not infer the framework from MSBuild version.
The application target framework is unchanged by either setting.

| MSBuild property | Default | Meaning |
|---|---|---|
| `RulesMSBuildToolTargetFramework` | `net10.0` | Framework of the adapter tool DLL |
| `RulesMSBuildEngineRoot` | `$(MSBuildBinPath)` | Directory supplying referenced engine assemblies |

Both projects import `tools/MSBuildTool.props`. Their Microsoft.Build references
use the supplied directory; GraphExport also takes NuGet.Versioning from it.
Supply a complete qualified engine/SDK layout, not just Microsoft.Build.dll.
The selected build SDK must support the tool framework, and the runtime that
loads the resulting tool must support that framework. Selecting these inputs
does not itself select or install a compiler SDK or runtime.

For example, in an SDK 11 tool-build workspace:

```sh
dotnet msbuild tools/GraphExport/GraphExport.csproj -restore -target:Build \
  -property:Configuration=Release \
  -property:RulesMSBuildToolTargetFramework=net11.0 \
  -property:RulesMSBuildEngineRoot=/path/to/qualified/msbuild \
  -getProperty:TargetPath,TargetFramework,RulesMSBuildEngineRoot
```

Use the same properties for ReplayPlugin. The normal repository checkout still
pins SDK 10.0.400; the native probe below creates SDK-11-pinned tool snapshots
rather than replacing that pin. Use separate build/output directories per profile.
The input directory supplies compile-time references; the process loading
ReplayPlugin must separately select the corresponding engine. GraphExport copies
its private references; ReplayPlugin intentionally uses its host's engine.

`prepare_graph.py` and `probe_replay.py` expose corresponding options:
`--tool-target-framework` and `--msbuild-engine-root`. The preparation Python API
accepts `tool_framework` and `engine_root`. Both callers consume MSBuild's reported
TargetPath from the successful build, instead of assuming a net10.0 output path.
Missing reported outputs are errors even when an older net10.0 DLL exists.

These are tool build inputs, not a completed multi-toolchain Bazel profile API.
Existing action declarations already consume the staged plugin DLL; this change
does not independently add a complete SDK/engine/host profile fingerprint to
preparation reuse. The [rule SDK follow-up](rule-toolchain-findings.md) adds
explicit SDK selection through application preparation and native action execution.
Net11 project contracts, general cross-profile caching and other probe callers'
fixed paths remain future matrix qualification work. Existing production SDK/runtime pins are unchanged.

## Native tool qualification

On macOS ARM64, the compiler build used the assembled SDK 11 Preview 7 /
MSBuild 18.10.1 toolset from the preceding matrix experiment. Changing only the
reference-engine and tool-framework inputs gave:

| Reference engine | Tool framework | GraphExport | ReplayPlugin |
|---|---|---|---|
| 18.9.6 | net10.0 | Build and load pass | Build passes |
| 18.9.6 | net11.0 | Build and load pass | Build passes |
| 18.10.1 | net11.0 | Build and load pass | Build passes |
| 18.10.1 | net10.0 | CS1705 rejection | CS1705 rejection |

The GraphExport check verifies that its copied Microsoft.Build.dll hash matches
the explicit reference-engine input. Loading each successful exporter reaches
its expected invalid-request diagnostic for a deliberately absent request,
proving executable startup rather than only compilation. Missing engine files
and conflicting TargetFramework versus RulesMSBuildToolTargetFramework also fail
for the expected diagnostics. Ten native expectations pass in total.

Run with the exact configuration/toolsets created by the matrix evaluation
(`codex/msbuild-1810-evaluation` worktree), choosing a new output directory:

```sh
python3 tools/probe_msbuild_tools.py \
  --matrix-config /tmp/msbuild-matrix-prepared/matrix-config.json \
  --toolsets /tmp/msbuild-matrix-qualified/toolsets \
  --output /tmp/msbuild-tool-inputs-controls
```

Raw evidence: `/tmp/msbuild-tool-inputs-controls/report.json`. SDK/runtime 11
versions remain previews; the exact package and archive identities are recorded
in the preceding matrix's configuration and pins. This script neither upgrades
installed SDKs nor edits source projects to manufacture a passing combination.

## Replay and regression evidence

- `nix develop -c bash scripts/check-dotnet.sh`: owned builds/format checks and
  all five code-style policy controls pass with the default SDK 10 inputs.
- `python3 -m unittest discover -s tests/msbuild_tools -v`: two tests pass,
  covering selection of the reported net11 artifact over a stale net10 artifact,
  rejection when the selected output is missing, and rejection of an unrelated DLL.
- `python3 -m unittest discover -s tests/graph_execution -p test_prepare_graph.py -v`:
  all 18 preparation rejection tests pass.
- `nix develop -c python3 tools/probe_replay.py --output /tmp/msbuild-default-tool-replay`:
  full default 18.9.6 replay probe passes, including relocation and negative controls.
- Separate-input 18.10.1 replay: tools compiled for net11.0 with SDK 11; application
  builds used SDK 10.0.400 with engine 18.10.1.42706 on the .NET 11 runtime.
  Same-path, producer-deleted relocation, App-only edit and Publish all compile
  only App, report a Shared replay hit, and run with the expected output.
  The existing payload/schema/property/root/target/artifact rejection controls
  also pass. This proves the selected net10 application replay slice, not net11
  application support or full Bazel acceptance with the new engine.
- `nix develop -c python3 tools/probe_graph_execution.py --root-project --output /tmp/msbuild-tool-root-preparation`: root-project native Bazel execution passes with the reported tool paths; output is `root-project`.
- A complete real 18.9.6 producer bundle is rejected by the 18.10.1 consumer with
  `dependency identity/version mismatch`, before either project compiles.

The separate-input replay uses the probe's new flags with the matrix dispatcher
at `/tmp/msbuild-tool-replay-launcher/dotnet`. Its tool-build branch selects the
SDK 11/18.10.1 compiler, its project-build branch selects SDK 10/18.10.1, and
application execution uses runtime 10. Reports retain actual commands and engine
version. Evidence is `/tmp/msbuild-explicit-tool-replay/report.json` and
`foreign-engine-canonical.json` beside it. These local paths are ephemeral.
The foreign-bundle check uses canonical workspace paths, as the replay contract
requires; an initial /tmp versus /private/tmp mismatch was an invalid probe setup.

The broader default diamond graph probe fails MSB4252 on App's request for Shared
with different TargetFramework globals. The unchanged af2f727 baseline reproduces
the same MSB4252/MSB4273 failure. This is recorded as a failing graph gate, not
reported as passing or repaired by the tool-input change. Evidence:
`/tmp/msbuild-tool-input-preparation/bazel.log` and
`/tmp/msbuild-tool-preparation-baseline/bazel.log`.

No Linux or GitHub CI run was dispatched. Full new-engine graph/cache/staging
qualification remains separate from clearing the tool compilation blocker.
