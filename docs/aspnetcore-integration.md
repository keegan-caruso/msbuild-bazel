# ASP.NET Core bootstrap integration slice

This implements the first integration slice for ASP.NET Core 10.0.0, revision
`7387de91234d3ef751fa50b3d1bfede4130213ff`. It is **not qualification of the full
ASP.NET Core repository or its Arcade SDK**.

## Generic APIs

`import_paths` maps a single-file label to its logical workspace-relative path.
It is an explicit input dependency, works with generated files, and preserves
normal project import order. Conflicting contents at a destination and unsafe
logical paths are rejected by the existing staging boundary.

```python
filegroup(
    name = "generated_props",
    srcs = [":bootstrap"],
    output_group = "Directory.Build.props",
)
msbuild_binary(
    name = "App",
    project = "app/App.csproj",
    target_framework = "net10.0",
    srcs = ["app/Program.cs"],
    import_paths = {
        ":generated_props": "artifacts/bin/GenerateFiles/Directory.Build.props",
    },
    reference_packages = [":primitives"],
)
```

`reference_packages` binds a bare Reference identity to a same-ID locked NuGet
package. It is a compile/runtime package dependency, including its declared
closure. The binding normalizes that Reference to PackageReference after SDK and
adapter imports but before declaration validation. Metadata is retained, normal
version/private-assets validation still applies, and the implicit flag permits
repositories whose policy requires Reference rather than direct PackageReference.
Exactly one matching Reference is required; HintPath, aliases, explicit
SpecificVersion, EmbedInteropTypes and ProjectPath are rejected. Unbound bare
references remain errors.

This is an explicit dependency choice, not an implementation of every repository's
custom reference resolver. BUILD authors must express the selected package version
and conditions (for example latest versus servicing baseline) explicitly. This
API does not infer them from ASP.NET Core's LatestPackageReference items. Project
references already resolved at evaluation retain existing project-edge validation.
Packages that need build/analyzer assets must also be declared in those roles.

Bound tool/output properties are checked on both restore and subsequent build or
generation evaluation, including after restored package imports become visible.

## Reproduction and evidence

Run `tests/explicit_msbuild/aspnetcore_integration.py <fresh-dir> <aspnet-checkout>`
with the qualified SDK/Bazel/repository-cache environment configured.

The fixture copies the real GenerateFiles.csproj, three templates, and
ResolveReferences.targets from the pinned checkout. A scoped harness supplies
explicit bootstrap properties and target-output bindings; it does not import the
repository-wide Arcade bootstrap. The package task and upstream target bodies are
unchanged. The consumer harness imports both generated MSBuild files and the
upstream custom reference targets and calls Microsoft.Extensions.Primitives.

Pinned archives include:

- Microsoft.DotNet.Build.Tasks.Templating 10.0.0-beta.25515.111;
- Microsoft.Extensions.Primitives 10.0.0;
- Microsoft.NETCore.App.Ref and Microsoft.NETCore.App.Host.linux-arm64 10.0.0.

All archives are SHA-256 verified. The framework/apphost packages are explicit
restore inputs because the generated framework settings request 10.0.0 whereas
the qualified SDK carries newer packs. No compilation-time network restore is
allowed.

On Ubuntu 22.04 ARM64, SDK 10.0.400 and Bazel 9.2.0:

- All three bootstrap outputs exactly match raw MSBuild bytes.
- Consumer output and reference assembly exactly match raw MSBuild.
- A template edit changes generated props and the consumer assembly version.
- Missing bindings, bindings without matching Reference, and HintPath metadata fail.
- After deleting the raw producer, first workspace and output base, both generation
  and compilation recover from disk cache in a relocated workspace/fresh user root.

See [recorded results](aspnetcore-integration-evidence.json). Existing worker
acceptance, .NET build/style/unit checks and toolchain/Starlark checks also passed.

## Remaining scope

External MSBuild SDK resolution (Arcade/Helix/SharedFramework), the original
repository-wide props/targets, actual managed assembly graph, signing/packaging,
SourceLink/versioning, native/Java/Node workloads and full-repository tests remain
unqualified. The fixture uses the qualified SDK, not upstream's preview SDK pin.
The generated live-framework lookup is disabled explicitly for the harness on
both raw and Bazel builds; it is not a live shared-framework integration.
Cache evidence here is disk-cache recovery, not HTTP transport or remote execution.
