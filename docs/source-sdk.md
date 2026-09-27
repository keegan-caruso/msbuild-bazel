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
