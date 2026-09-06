# Public API replay findings

The Release/net10.0 two-project fixture can replay Shared's target results at a
new workspace path through the public project-cache API with strict project
isolation. This does not establish Bazel action or remote-cache correctness.

## Experiment

Run in the pinned development environment:

```sh
python3 tools/probe_replay.py --output artifacts/replay-probe
python3 -m unittest discover -s tests/e2e -v
```

The new process contract is [replay-interface.md](replay-interface.md). The probe
builds its plugin against the SDK's own Microsoft.Build assemblies, without
adding NuGet dependencies or changing toolchain pins. It captures a producer
App graph build requesting `Build;Publish`, recording Shared's completed target
results through `HandleProjectFinishedAsync`. Thus the producer builds both
projects; it is not yet a Bazel action that builds only Shared. Subsequent fresh
processes reconstruct `PluginTargetResult` values for Shared and return a cache
hit. App builds normally. All compilation commands retain `-graphBuild
-isolateProjects`; no `BuildProjectReferences=false` override is used.

The graph's inferred Shared contract, inspected with
`ProjectGraph.GetTargetLists(["Build", "Publish"])`, is:

- `GetTargetFrameworks`
- `Build`
- `GetNativeManifest`
- `GetCopyToOutputDirectoryItems`
- `GetTargetFrameworksWithPlatformForSingleTargetFramework`
- `GetCopyToPublishDirectoryItems`

The last target is needed for the narrow publish request. The payload captures
all six, including successful empty results. A Build replay requests the first
five. The plugin checks every requested target before returning a hit.

## Observations

Measured on macOS ARM64 with Nix's .NET SDK 10.0.100 and MSBuild
18.0.2.52411. The first successful retained run is `artifacts/replay-4/report.json`.
That run cleaned bin and configuration-specific obj outputs. The finalized
acceptance test additionally removes entire bin/obj directories and restores
only the pre-build NuGet metadata snapshot before staging Shared artifacts.

| Case | Result |
| --- | --- |
| Same-path replay | App alone compiles; `shared-v1/app-v1` |
| Relocated replay, producer deleted | App alone compiles; `shared-v1/app-v1` |
| App-only edit at consumer | App alone compiles; `shared-v1/app-v2` |
| Publish at consumer | App alone compiles; published DLL runs as `shared-v1/app-v2` |
| Missing payload, Build target set, or publish-only result | Dependency error, no compilation |
| Missing artifact | Dependency error before MSBuild |
| Global properties, framework, roots, SDK, engine or schema mismatch | Dependency error, no compilation |
| Unsupported external result path | Dependency error, no compilation |

The consumer is copied independently from the source fixture and restored with
its own `.nuget/packages` root. The producer is removed before its first replay.
Only workspace-relative Shared bin and obj/Release artifacts are transported;
project.assets.json and generated NuGet imports belong to the consumer restore.
The manifest records size and SHA-256 for each artifact. The runner validates the
bundle before staging, and the plugin validates the staged files before a hit.

Metadata uses explicit workspace, NuGet and SDK root tokens, preserving escaped
item specifications, custom metadata and item order. Output roots are beneath
the workspace in this fixture. Unknown absolute path forms and unknown root
tokens fail; this intentionally narrow path recognizer is not a general parser
for arbitrary metadata formats. Explicit root mappings and the evaluated target framework are validated before
replay. The current fixture exercises workspace paths;
NuGet and SDK substitutions need richer dependency fixtures for evidence.

## Validation

On 2026-09-05, using the installed Nix SDK and Bazel through explicit
`SPIKE_DOTNET_ROOT` / `SPIKE_BAZEL` overrides:

- `bash scripts/check.sh`: passed pinned version and scaffold checks.
- `python3 -m unittest discover -s tests/e2e -v`: all eight tests passed in
  41.690 seconds, including the seven unchanged boundary/path controls and the
  replay probe's four positive and eleven negative cases.
- `git diff --check`: passed.

The first complete suite run exposed missing diagnostics when plugin exceptions
were thrown. Replay rejection now calls `PluginLoggerBase.LogError` and returns
`CacheResultType.None`; the final suite verifies dependency diagnostics and no
compilation for every rejection case. No Linux execution was performed locally.

## Limits and next step

Global properties in the observed graph are `Configuration=Release` and
`IsGraphBuild=true`; net10.0 is an evaluated fixture property. Matching those and
tool versions is a compatibility check, not a complete action identity. No source,
import, environment or SDK-content fingerprint is implemented. Arbitrary package
build targets, side effects, symlinks, multi-targeting and custom output roots
remain unsupported. Artifact contents, including PDBs and incremental-state
files, can still contain producer paths; they are not normalized.

Linux validation is left to CI/the pinned Linux environment. Native macOS success
does not prove Linux or cross-platform replay. The raw-cache path controls remain
independent: raw serialization still cannot move project identities.

Next define the Bazel two-target execution-log acceptance harness and producer
Shared-only action contract, then test this replay boundary across actual action
paths and sandbox inputs. Restore and tool acquisition remain outside compile
actions. Disk-cache and remote-cache claims require their own measurements.
