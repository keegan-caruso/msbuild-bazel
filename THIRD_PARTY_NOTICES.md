# Third-party material

The root [MIT license](LICENSE) covers this project's original code and documents.
It does not replace the licenses of third-party material.

## Tools and qualification dependencies

Bootstrap and qualification scripts download .NET SDK/MSBuild, Bazel, Buildifier,
NuGet packages and pinned upstream project sources. These remain governed by their
respective licenses and notices. Package locks, source revisions and artifact
hashes record acquisition provenance; they do not grant redistribution rights.
Downloaded tools and upstream checkouts are not part of this source distribution.

The graph and artifact tooling bootstraps copy MSBuild and NuGet support assemblies from the
SDK into its ignored build output. A future binary release must include the
licenses and notices for those redistributed dependencies. This repository does
not currently publish a binary distribution of the active runner.
