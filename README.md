# MSBuild rules for Bazel

Build, test, and cache .NET project graphs with Bazel while keeping standard `.csproj` files and MSBuild SDK behavior.

- **Explicit inputs:** sync evaluated projects into committed Bazel declarations.
- **Two-level reuse:** Bazel caches whole actions; the MSBuild plugin reuses unchanged projects in changed graphs.
- **Precise compiler inputs:** qualify SDK-selected DLLs, reuse compilation when those bytes match, and refresh runtime copies.
- **Declared toolchains:** use a downloaded or source-built SDK with an optional execution-runtime override.
- **Bazel tests and artifacts:** run executable, MTP, and VSTest tests; export layouts, packages, and published apps.

## Start here

See the [quick start](examples/quickstart/README.md) ([downloaded SDK](examples/quickstart/README.md#downloaded-sdk), [source-built SDK](examples/quickstart/README.md#source-built-sdk)) and [source-to-app workflow](examples/source-runtime-app/README.md) for a source-built execution runtime. Requires Bazelisk and OS .NET prerequisites. Pins: SDK **11.0.100**; Bazel **9.3.3**.

**Experimental:** consume a pinned source checkout (no BCR or runner release; API may change). See [validated scope and limits](docs/support.md).

## Measured progress

On a scoped dotnet/runtime graph (**543 configurations / 481 compilations**), an independent Linux ARM64 worker recovered all build actions and nine cached test results in **14.15 s** (median of three runs). Separate correctness runs executed **118,952 tests (64 skips)** with tools, packages, and native prerequisites prepared. See [performance](docs/performance.md) for raw MSBuild comparisons, edit costs, and reproduction.

[Design](docs/design.md) · [API](docs/api.md) · [Support](docs/support.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [MIT license](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)
