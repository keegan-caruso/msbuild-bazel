# Third-party material

The root [MIT license](LICENSE) covers only this project's original code and docs, not third-party material.

## Tools and qualification dependencies

Bootstrap and qualification scripts download .NET SDK/MSBuild, Bazel, Buildifier, NuGet packages, and pinned upstream sources; each remains under its own license/notice. Package locks, source revisions, and artifact hashes record provenance only, not redistribution rights. Downloaded tools and upstream checkouts are not part of this source distribution.

Graph and artifact tooling bootstraps copy MSBuild and NuGet support assemblies from the SDK into ignored build outputs. Any future binary release must include licenses/notices for those redistributed dependencies; no binary runner distribution is currently published.
