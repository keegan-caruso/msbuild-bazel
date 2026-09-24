# MSBuild rules for [Bazel](https://bazel.build)

`rules_msbuild` gives Bazel explicit .NET project dependencies and remote caching
while retaining SDK-style `.csproj` files and MSBuild compilation.

**Experimental:** the API may change. Use the rules from source; there is no
published runner package or Bazel Central Registry release.

## Get started

Follow the [setup guide](docs/development.md), then run the
[library, application and test example](examples/hello/README.md).
Declare projects with [`msbuild/defs.bzl`](msbuild/defs.bzl).

Supported baselines: .NET SDK **10.0.400**, Bazel **8.8.0 / 9.2.0** (default).
Platform and workload limits are listed in [current support](docs/implementation-plan.md).

## Documentation

- [Rule API](docs/explicit-bazel-rules.md) and [tests](docs/bazel-test.md)
- [Performance versus raw MSBuild](docs/performance.md)
- [Remote execution](docs/remote-execution.md) and [Linux workers](docs/explicit-linux-workers.md)
- [Roadmap](docs/roadmap.md) and [all documentation](docs/index.md)

## Contributing

See [contribution guidance](CONTRIBUTING.md) and [security reporting](SECURITY.md).
GitHub CI is manual-only. Original code is [MIT licensed](LICENSE);
[third-party notices](THIRD_PARTY_NOTICES.md) cover adapted material.
