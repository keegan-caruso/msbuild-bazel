# MSBuild rules for Bazel

Build, test and cache .NET project graphs with Bazel, keeping normal `.csproj`
files and MSBuild's SDK behavior.

- **Explicit inputs:** sync evaluated projects into committed Bazel declarations.
- **Reuse at two levels:** Bazel caches whole actions; the MSBuild plugin reuses
  unchanged projects inside a changed graph.
- **Precise compiler inputs:** qualify the DLLs the SDK actually selects, reuse
  compilation when those bytes stay unchanged, and refresh runtime copies.
- **Declared toolchains:** use a downloaded SDK or one produced by your source
  build, with an optional execution-runtime override.
- **Bazel tests and artifacts:** run executable, MTP and VSTest tests; export
  layouts, packages and published apps.

## Start here

The [quick start](examples/quickstart/README.md) has separate
[downloaded SDK](examples/quickstart/README.md#downloaded-sdk) and
[source-built SDK](examples/quickstart/README.md#source-built-sdk) scenarios.
For a source-built execution runtime, see the [source-to-app workflow](examples/source-runtime-app/README.md).
Requires Bazelisk and OS .NET prerequisites. Pins: SDK **10.0.400**;
Bazel **8.8.0 / 9.3.0** (default).

**Experimental:** consume a pinned source checkout. No BCR or runner release;
the API may change. See [validated scope and limits](docs/support.md).

## Measured progress

On a scoped dotnet/runtime graph with **543 configurations / 481 compilations**,
an independent Linux ARM64 worker recovered all build actions and nine cached test
results in **14.15 s** (median of three runs). Separate correctness runs actually
executed **118,952 tests, with 64 skips**. Tools, packages and native prerequisites
were prepared; see [performance](docs/performance.md) for raw MSBuild comparisons,
edit costs and reproduction.

[Design](docs/design.md) · [API](docs/api.md) · [Support](docs/support.md) ·
[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) ·
[MIT license](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)
