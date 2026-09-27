# Building the SDK from source

This qualification targets .NET SDK 10.0.100 on Linux ARM64, starting from
`dotnet/dotnet` revision `b0f34d51fccc69fd334253924abd8d6853fad7aa`.
It does not change the default downloaded SDK or claim a complete Bazel source
SDK build yet. The existing [SDK artifact contract](sdk-toolchains.md) accepts
the eventual produced executable and complete SDK payload.

## Source and bootstrap inventory

[The pin](../tests/source_sdk/pin.json) records the source archive digest,
qualification container image, source-build configuration, bootstrap versions,
and hashes of the reviewed upstream build definitions. The source archive
contains 25 repository entries and 13 submodule entries. Its runtime revision
is the same `60629d14374c56f1cb51819049ad1fa529307f8d` used by our prior runtime
qualification; that selected slice is not a complete SDK runtime payload.

The upstream `global.json` requests SDK `10.0.100-rc.2.25502.107` and Arcade
`10.0.0-beta.25502.107`. Preparation also consumes previously source-built
artifacts `10.0.100-rc.2.25502.107`. Bootstrap inputs and final shipped outputs
must be audited separately. A source-built SDK still requires a bootstrap.

To inventory a pristine extracted source tree:

```sh
python3 tests/source_sdk/inventory.py /path/to/vmr /tmp/sdk-inventory.json
python3 -m unittest discover -s tests/source_sdk -v
```

The inventory rejects changed pinned definitions. Repository reference
conditions, metadata and shared update/remove operations remain verbatim. This
is a review inventory, **not an evaluated dependency graph**. MSBuild must
evaluate the selected configuration before producing Bazel dependency edges.
In particular, upstream flows generated package-version props and dependency
packages between repository builds; merely copying `RepositoryReference`
elements into Bazel would omit behavior.

## Qualification sequence

1. Pin sources, bootstrap inputs and native environment; inventory dependencies.
2. Establish the upstream source-only baseline and record payload and resource use.
3. Prove synthetic tool/package handoff, then one real source component.
4. Expand declared component/project producers while retaining upstream semantics.
5. Assemble the complete SDK and register it through `msbuild_sdk`.
6. Qualify console, project/package references, tests, publish, ASP.NET and Razor
   with the bootstrap SDK inaccessible to consumers.
7. Measure body/API edits and independent remote-cache recovery at another path.
8. Rebuild with the produced SDK; separately measure reproducibility.

Only the definition inventory and its two negative/semantic checks have passed
so far. Acquisition of the pinned source archive succeeded (about 460 MiB
compressed, 3.3 GiB extracted). Upstream bootstrap preparation is in progress.
No full SDK baseline, Bazel component build, cache recovery or self-hosting result
is claimed here.

Upstream references: [VMR build instructions](https://github.com/dotnet/dotnet/tree/b0f34d51fccc69fd334253924abd8d6853fad7aa#building),
[source-build requirements](https://github.com/dotnet/source-build/blob/main/Documentation/system-requirements.md).

## Generated package handoff

`msbuild_generated_nuget_package` consumes a declared Bazel action's `.nupkg`
output. Package ID and version remain explicit analysis-time inputs; the NuGet
content hash is computed from the produced bytes during extraction. Source-file
archives are rejected by this rule. Acquired archives still use
`msbuild_nuget_package` with mandatory SHA-256 and NuGet content hashes.

```python
msbuild_generated_nuget_package(
    name = "source_package",
    package_id = "Source.Package",
    version = "1.0.0",
    archive = ":pack",
)
```

Use this package in `deps`, `build_deps`, or other existing package roles and in
an explicit `msbuild_package_lock`. Declaring a package in the lock alone does
not authorize it as a project's direct dependency.

The `tests/source_sdk/package_handoff.py` synthetic uses actual SDK `Pack`
through `msbuild_generate`, then consumes the resulting package offline. On
macOS ARM64 / Bazel 9.2.0 / downloaded SDK 10.0.400, initial execution and body-edit
execution passed; mismatched package identity, missing producer output, and a
source-file archive were rejected. Thirteen package extraction unit checks also
passed, including the new generated content-hash, identity and path controls.
This establishes the handoff mechanism, not a real upstream SDK component build.

## Upstream baseline issues

The initial preparation failed because the minimal toolchain image lacked
`file`. Adding the pinned source's native prerequisites and `file` allowed its
binary scan to complete; it removed 743 disallowed checked-in binaries.

The first source build failed in IdentityModel: its wall-clock-derived file
version became `8.0.0.70927`, exceeding the valid revision range. The qualification
patch in `tests/source_sdk/patches/identitymodel-file-version.patch` passes
`FileVersion=<declared release version>.0` to that component's nested builds.
It does not disable compiler warnings or source-build binary checks.

Retrying the failed tree exposed external-package patch stamps surviving while
`PrepareInnerClone` recopied original source files. The current attempt uses a
fresh extraction and fresh package state. The bootstrap archive and SDK are the
only reused build inputs. `tests/source_sdk/baseline.sh` records the commands for
a fresh source tree; native package versions must be retained with its evidence.
