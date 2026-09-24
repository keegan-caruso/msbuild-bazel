# Contributing

This project is experimental. Start with the [README](README.md),
[rule API](docs/explicit-bazel-rules.md) and
[current qualification boundary](docs/implementation-plan.md).

For a bug, include a small reproducer, SDK/Bazel versions, OS/architecture, the
command, expected behavior and actual result. Remove credentials and proprietary
source before sharing logs. Binlogs can contain environment variables and project
contents; share only a reviewed, minimal example. Use the [security policy](SECURITY.md)
for a suspected vulnerability.

## Development

1. Fork/clone the repository and create a focused branch.
2. Follow [development setup](docs/development.md) or use the pinned Nix shell.
3. Keep production rules generic. Make sources, dependency edges, tools and
   configuration explicit in Bazel; retain MSBuild's SDK behavior.
4. Add a small synthetic control for changed behavior, including invalidation or
   failure cases when relevant. Preserve upstream projects when claiming real-project
   compatibility, and document the exact platform and scope tested.
5. Run checks relevant to the change:

   ```sh
   bash scripts/check.sh
   bash scripts/check-dotnet.sh
   ```

   For project-rule behavior, also run the explicit acceptance harness following
   [the rule guide](docs/explicit-bazel-rules.md#local-toolchain-setup-and-reproduction).
   Large qualification suites are not required for documentation-only changes.
6. Open a pull request describing the problem, resulting behavior, validation and
   remaining limits. Do not commit downloaded tools, build products or private logs.

GitHub workflows are manual-only and are run when a maintainer explicitly requests
CI. A workflow definition or an untested platform configuration is not passing evidence.
The contributor guidance in [AGENTS.md](AGENTS.md) also applies to automated changes.

Contributions to original project code are under the repository's [MIT license](LICENSE).
Preserve third-party license notices and identify imported or adapted material.
