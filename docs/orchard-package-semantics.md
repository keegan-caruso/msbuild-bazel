# Explicit package semantics

The first Orchard compatibility fix retains original NuGet package metadata while
pinning the declared package graph. Central `PackageVersion` entries supply the
lock version when central management is enabled. Original versions and version
ranges must agree with the lock, and restored package identities are checked
against it. Implicit SDK package references keep their SDK behavior.

`package_private_assets = {"Package.Id": "all"}` declares private direct packages.
The default is `none`; explicit values must match the evaluated project. Private
package closures remain available to the producer but are not exported as
consumer compile references. Partial PrivateAssets masks, VersionOverride,
GeneratePathProperty, and package aliases remain unsupported and fail closed.
Existing IncludeAssets and ExcludeAssets metadata is retained alongside explicit
Bazel package roles. One locked version per package ID is still required.

## Linux qualification

SDK 10.0.400 / Bazel 8.4.2, ARM64 Apple container, persistent MSBuild workers:

- The unchanged OrchardCore.SourceGenerators project at Orchard commit
  `04467a3438d4255627c1a478598a1585b3ff2947` builds as netstandard2.0 using its
  central versions and private packages. Its `.editorconfig` and analyzer release
  AdditionalFiles are declared inputs. SDK-generated .NET Standard Reference
  items are preserved.
- Central-package fixture builds without NU1008.
- `tests/explicit_msbuild/package_semantics.py`: private producer compilation,
  consumer compile exclusion, privacy mismatch rejection, public compile flow,
  central lock mismatch rejection, range acceptance, and recovery pass.
- Raw MSBuild and the explicit rule both fail to run a consumer that depends on
  a producer's private-only package at runtime. The compile visibility test does
  not promise runtime propagation that raw NuGet does not provide.
- Existing worker/shared-restore acceptance passes, including isolation,
  tool replacement, failure/recovery, and deleted-producer cache relocation.
- MTP pass, intentional assertion failure, metadata/version mismatch rejection,
  and recovery pass with real locked packages.

Reproduce the controls after `acceptance.py /tmp/package-check`:

```sh
python3 tests/explicit_msbuild/package_semantics.py /tmp/package-check
python3 tests/explicit_msbuild/mtp.py /tmp/package-check /path/to/mtp-lock
```

These are correctness results, not an Orchard performance benchmark. Project-built
analyzer edges and referenced-target/module asset handoff are subsequent steps.
