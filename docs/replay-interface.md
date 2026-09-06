# Experimental replay protocol v1

`python3 tools/probe_replay.py --output ABSENT_DIRECTORY` builds the plugin with
SDK 10.0.100, copies the fixture, restores separately, captures Shared results,
and tests same-path and relocated graph replay. Each compilation invocation is a new
MSBuild process with `-graphBuild -isolateProjects` and Release. The producer is deleted
before relocated consumption. The v1 `spike.py` protocol is unchanged.

The plugin uses environment variables `SPIKE_REPLAY_MODE` (capture/replay),
`SPIKE_REPLAY_WORKSPACE`, and `SPIKE_REPLAY_BUNDLE`. These are orchestration
settings, not project global properties. `results.json` contains schemaVersion 1,
SDK and engine versions, workspace-relative project, evaluated target framework,
explicit root mappings, complete global properties,
requested targets, and ordered output items with escaped item specifications and
escaped custom metadata. Declared workspace, NuGet, and SDK roots are tokenized;
unknown absolute paths are rejected. Artifacts are separate files listed in
`artifacts.json` with relative paths, sizes and SHA-256 hashes.
Root mappings declare `${WORKSPACE}` as the action workspace, `${NUGET}` as
`${WORKSPACE}/.nuget/packages`, and `${SDK}` as `dotnet-sdk:10.0.100`; the
consumer binds that SDK role to the loaded Microsoft.Build assembly directory.
Shared bin and configuration-specific obj files are staged; consumer restore owns project.assets
and generated NuGet imports. This is a narrow fixture contract, not an input key.

A replay must validate identity, all requested target results, and every artifact
before returning a hit. Missing dependencies must fail, never compile Shared.
`report.json` records platform, SDK/engine, commands, statuses, logs, compilation
markers and runtime output. Negative cases must fail with no compilation markers.
The narrow Publish request uses the same captured dependency result bundle.
