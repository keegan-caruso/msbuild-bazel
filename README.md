# MSBuild rules for [Bazel](https://bazel.build)

Bazel schedules and caches declared .NET graphs. MSBuild keeps project evaluation,
SDK targets and compilation; its cache plugin reuses projects inside each graph.

**Experimental:** use the rules from source; the API may change. There is no runner
package or Bazel Central Registry release.

Start with the [quickstart](examples/quickstart/README.md): select an SDK in
`global.json`, keep normal `.csproj` files, and run sync to generate graph contracts.
Bazel supplies the SDK. Baselines: SDK **10.0.400**, Bazel **8.8 / 9.2** (default).

- [Graph API](docs/graph-workflow.md), [sync](docs/project-sync.md), [tests](docs/bazel-test.md)
- [Current support](docs/implementation-plan.md) and [performance](docs/performance.md)
- [All docs](docs/index.md) and [contributing](CONTRIBUTING.md)

Original code is [MIT licensed](LICENSE); see [third-party notices](THIRD_PARTY_NOTICES.md).
GitHub CI is manual-only.
