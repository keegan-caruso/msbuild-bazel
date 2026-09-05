# msbuild-bazel

A spike exploring Bazel project-level scheduling and caching while retaining MSBuild, NuGet, and the .NET SDK build behavior.

**Status:** Codex setup, CI, and the first MSBuild boundary experiment are implemented. A Bazel project rule and graph exporter are not implemented yet.

## Quick start

Linux x86-64 (glibc), with Bash, Python 3, curl, tar, and standard .NET runtime dependencies:

```sh
bash scripts/setup.sh
bash scripts/check.sh
bash scripts/dotnet.sh --info
bash scripts/bazel.sh version --gnu_format
```

Setup installs checksum-pinned .NET SDK 10.0.100 and Bazel 8.4.2 into ignored `.tools/` directories without sudo. These are fixed experimental baselines, not a claim to be the latest releases. Bazel's distribution includes its JDK. The wrapper uses batch mode for short-lived agent containers. Setup is repeatable and needs internet access only for missing downloads. Use the wrappers in each new shell; setup exports do not persist into Codex's agent session.

## Codex cloud environment

Select this repository in the Codex environment settings and configure:

- Setup script: `bash scripts/setup.sh`
- Maintenance script: `bash scripts/setup.sh`
- No secrets required for this scaffold.

The script lives in the repository; committing it does not configure the hosted environment automatically. Setup downloads from `builds.dotnet.microsoft.com` and `releases.bazel.build`. Future NuGet dependencies must be restored during setup before agent-phase offline builds can work.

Codex reads [AGENTS.md](AGENTS.md) for project context and commands. See the [spike plan](docs/spike-plan.md) for the next implementation steps.

## Spike contracts and tests

The [interface contract](docs/interfaces.md) and [e2e scope](docs/e2e-scope.md) were committed before the driver implementation. Run the six black-box scenarios with:

```sh
python3 -m unittest discover -s tests/e2e -v
```

Tests copy the two-project fixture to fresh temporary directories. Restore downloads the pinned Traversal SDK from NuGet into each workspace's own package directory; tests currently require network access. Compilation is then invoked separately without restore.

The first milestone exports a Shared project's MSBuild result cache and bin/obj artifacts, removes local build outputs, and consumes that bundle in an isolated App build. It also tests an App-only edit and rejects missing artifacts, mismatched configuration, and workspace relocation. Failed workspaces are retained for diagnosis.

This is a same-path handoff experiment, not a general Bazel adapter or proof of portable caching. See the [findings](docs/findings.md) and the next milestone in [e2e scope](docs/e2e-scope.md).

## Validation

`bash scripts/check.sh` checks shell syntax, version-pin consistency, and installed tool versions. It does not run the integration experiments. GitHub Actions separately runs fresh setup, repeated setup, Bazel package loading, and the e2e suite.

## References

- [Codex repository instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Codex cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environment)
- [MSBuild static graph](https://github.com/dotnet/msbuild/blob/main/documentation/specs/static-graph.md)
- [MSBuild Traversal](https://github.com/microsoft/MSBuildSdks/tree/main/src/Traversal)
