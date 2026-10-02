# MSBuild rules for [Bazel](https://bazel.build)

Build and cache .NET graphs with Bazel while keeping normal `.csproj` files and
MSBuild compilation.

Start with the [quickstart](examples/quickstart/README.md).
Requires Bazelisk; Bazel supplies the SDK. Baselines: SDK **10.0.400**,
Bazel **8.8.0 / 9.2.0** (default).

**Experimental:** the API may change; use from source. No BCR or runner release.

- [Design](docs/design.md) — ownership, execution and cache invalidation
- [API](docs/api.md) — sync, builds, tests and caching
- [Support](docs/support.md) — validated scope and limits
- [Performance](docs/performance.md) — comparison with raw MSBuild

[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) ·
[MIT license](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)
