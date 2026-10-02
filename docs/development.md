# Development

Applications need Bazelisk and normal OS .NET prerequisites; the SDK extension
supplies their SDK. Follow the [quickstart](../examples/quickstart/README.md).
Repository contributors also use pinned bootstrap tools:

```sh
bash scripts/setup.sh
source scripts/env.sh
bash scripts/check.sh
bash scripts/check-dotnet.sh
bash scripts/check-analysis.sh
python3 tests/graph_build/acceptance.py /tmp/fresh-graph-acceptance
```

Setup downloads SDK 10.0.400, Bazelisk 1.29.0, Buildifier and Buildozer 8.2.1 into
ignored local tool/cache directories. Use wrappers and explicit tool overrides;
do not depend on PATH changes. Production builds use no Python; Python drives
fixtures and reports.

`check.sh` checks shell syntax, pins, tool versions and tracked Starlark formatting.
`check-dotnet.sh` builds/formats Tooling, ArtifactTools, ProjectSync and GraphBuild,
treats warnings as errors and runs style/bootstrap/sync regressions. Fixture
projects retain their own build policy. `check-analysis.sh` uses rules_testing and
an aquery metadata check with an execution-disabled fake SDK.

## Versions and overrides

`.bazelversion` selects 9.2.0; `USE_BAZEL_VERSION=8.8.0` selects the other supported
baseline. Bazelisk acquires Bazel; the repository does not manage its checksums.

- `scripts/bazel-launcher.sh` retains the caller's workspace.
- `scripts/bazel.sh` runs from this repository's root.
- `scripts/dotnet.sh` selects the pinned contributor SDK.
- `RULES_MSBUILD_BAZELISK` / `BAZELISK_HOME` select launcher/cache.
- `RULES_MSBUILD_BAZEL` selects an explicit executable;
  `RULES_MSBUILD_BAZEL_VERSION` supplies its expected version.
- `RULES_MSBUILD_DOTNET_ROOT` selects contributor/fixture tooling, not a host-path
  SDK repository for application builds.

Use fresh disposable fixture/report directories. Do not commit SDKs, packages,
products or private logs. Keep profiling off for scores. CI is
[manual-only](ci-scope.md). Linux worker checks require the
[qualified container](apple-container-runbook.md).

## SDK selection

The SDK extension accepts an exact version or tracked `global_json` label.
Selection resolves against the pinned catalog; it never searches installed SDKs.
Unsupported roll-forward policies, machine-local paths, unknown fields/pins and
workloads fail explicitly. `msbuild-sdks` metadata does not acquire packages;
package SDKs require declared archives. Downloaded/generated SDKs use the same
[artifact contract](sdk-toolchains.md).
