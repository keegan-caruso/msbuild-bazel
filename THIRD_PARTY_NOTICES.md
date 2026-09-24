# Third-party material

The root [MIT license](LICENSE) covers this project's original code and documents.
It does not replace the licenses of third-party material.

## Buildbarn deployment fixture

`tests/explicit_msbuild/buildbarn/*.jsonnet` and `common.libsonnet` adapt the bare
configuration from [buildbarn/bb-deployments](https://github.com/buildbarn/bb-deployments),
revision `a35485609467dd70cd44c78b4735e5835061df5a`, under Apache License 2.0.
The original [license](tests/explicit_msbuild/buildbarn/LICENSE) is retained.
Local changes use a native filesystem worker, two ARM64 execution slots and a
qualification-specific platform identity. Acquisition/startup scripts and evidence
are maintained by this project. Downloaded Buildbarn binaries retain their own
upstream licenses; they are not checked into this repository.

## Tools and qualification dependencies

Bootstrap and qualification scripts download .NET SDK/MSBuild, Bazel, Buildifier,
NuGet packages and pinned upstream project sources. These remain governed by their
respective licenses and notices. Package locks, source revisions and artifact
hashes record acquisition provenance; they do not grant redistribution rights.
Downloaded tools and upstream checkouts are not part of this source distribution.

The ExplicitBuild bootstrap copies MSBuild and NuGet support assemblies from the
SDK into its ignored build output. A future binary release must include the
licenses and notices for those redistributed dependencies. This repository does
not currently publish a binary distribution of the active runner.
