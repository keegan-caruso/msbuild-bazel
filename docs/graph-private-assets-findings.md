# Ordinary SDK PrivateAssets baseline for R02

`tools/graph_private_assets.py` supplies a reusable Left-only package fixture and
an ordinary MSBuild oracle. Its `configure(workspace, package_feed,
version='1.0.0', private_assets=None)` function requires a feed inside the workspace,
records that feed relatively in NuGet.Config, and adds exact `[version]`
`Spike.Binary` metadata to `src/Left/Left.csproj`. It reuses the deterministic
`binary_inputs.Packages` ref/lib archives, including transitive `Spike.Leaf`.
Only Left's source uses the package. The returned binary version is rendered as
`package-v1`/`package-v2`; the call still executes the transitive Leaf assembly.

## Measured ordinary behavior

All four configurations restore and build the Release/net10.0 diamond successfully.
The explicit default value is `contentfiles;analyzers;build`; omitted metadata is
measured separately. The package inventories below include both Spike.Binary and
Spike.Leaf, version 1.0.0.

| PrivateAssets | Left restore | App restore and direct compile access | App copies package DLLs | Isolated App execution |
| --- | --- | --- | --- | --- |
| omitted | both packages | both packages; compile succeeds | both runtime DLLs | succeeds |
| explicit default | both packages | both packages; compile succeeds | both runtime DLLs | succeeds |
| all | both packages | neither package; direct access fails CS0103 | neither DLL | fails FileNotFoundException for Spike.Binary |
| none | both packages | both packages; compile succeeds | both runtime DLLs | succeeds |

Shared and Right have no package assets in every case. Left retains the reference
and runtime selections in its assets file, but as an ordinary SDK library it does
not copy these DLLs into its own bin directory under the fixture defaults.
For the three successful App cases, output is exactly
`shared-v1:left/package-v1|shared-v1:right`. Copy evidence compares the deployed
DLLs to the installed `lib/net10.0` and `ref/net10.0` hashes; runtime payloads and
reference assemblies differ. Successful execution runs from a copied output
directory with an isolated CLI home/package root, outside the source tree.

Each case first measures the unmodified App's build, output inventory and runtime.
Only afterward does a separate compiler control add a direct `Spike.Binary` API
call to App without changing restore assets. This distinguishes App's own compile
visibility from Left's ability to use its package.

## Adapter requirement and limits

The baseline does **not** justify copying Left's private package closure into App
or adding private references to App's compilation. `PrivateAssets=all` in this
specific fixture builds successfully but leaves a runtime dependency unavailable.
The adapter should reproduce or explicitly reject that behavior, not silently
repair it by broadening App's package closure. Conversely, the omitted/default/none
cases require App's own transitive restore closure; Left's project bundle alone is
not a substitute for App's declared package inputs.

These are ordinary MSBuild measurements, not generated-adapter acceptance. They
cover managed ref/lib assets and default library copy behavior, not Pack,
`CopyLocalLockFileAssemblies=true`, explicit content-copy items, native/RID assets,
or every category controlled by PrivateAssets. The local package feed is declared
relatively so upgrading only Left's package does not change root NuGet.Config.

## Commands and evidence

Under the pinned toolchain:

```sh
python3 tools/graph_private_assets.py --output artifacts/private-assets-baseline
python3 -m unittest discover -s tests/graph_packages -p test_private_assets.py -v
```

The probe retains each mode's assets, build/restore/visibility/runtime logs and
`report.json`, including package identities, selected ref/lib paths, output
inventories and hashes. Initial native macOS ARM64 evidence was retained at
`/private/tmp/msbuild-r02-privateassets-evidence`; SDK 10.0.100/MSBuild
18.0.2.52411 supplied the ordinary baseline. Linux requires the integrated CI
lane; no cross-platform claim follows from this local result.

The executable four-case test passed on macOS ARM64 in 15.8 seconds, including
runtime/reference hash assertions. Final test evidence is retained under
`graph-private-assets-7lcdolak/probe` in the native temporary directory.

## Generated adapter parity

`tests/graph_packages/test_private_assets_adapter.py` compares all four modes with
this ordinary oracle. Each mode has a cold native sandbox build and a second
build after adding a direct package API call only to App. The generated per-node
package manifests exactly match ordinary restore inventories. Cold execution
includes all four projects; the direct-call change executes App alone, with
producer bundles recovered from the local disk cache.

Omitted/default/none reproduce the successful runtime output and package DLL copy
set. `all` reproduces successful compilation of the original App, its absent
package DLLs, and the same isolated runtime FileNotFoundException. Direct App
access to the private package fails with CS0103 and publishes no completion seal.
The successful direct-access cases compile successfully. Compile diagnostics are
read only for executed actions: Bazel can prune unrequested diagnostics when
recovering producer bundles from cache. Raw execution records establish reuse.

The native macOS ARM64 parity test passed in 86.2 seconds against the R02 package
adapter, with evidence at `graph-private-adapter-qvpdk1s4` in the native temporary
directory. A subsequent check of all eight package-DLL hash/absence comparisons
against those retained outputs passed; the test now asserts those hashes too.
Run the test with:

```sh
python3 -m unittest discover -s tests/graph_packages -p test_private_assets_adapter.py -v
```

This extends the measured claim from ordinary MSBuild to generated native macOS
actions for these four configurations. Linux acceptance remains an integrated CI
gate. It does not change the deliberate runtime failure of the `all` fixture or
claim support for additional package asset categories.

The integrated `fd96f5e` run passed both baseline and adapter tests in 101.612
seconds, including the strengthened payload-hash assertions. Evidence:
`graph-private-assets-q_qm3pmi/probe` and `graph-private-adapter-46jzosv_` in the
native temporary directory. This run precedes the stale-restore review fixes.
## Restore metadata freshness

Graph export now compares evaluated direct `PackageReference` identities, exact
versions and `PrivateAssets` against the corresponding restored framework's
project dependencies, before publishing a manifest. This includes metadata from
imports and property expansion, and detects removed references as well as changed
ones. `PrivateAssets` supports omitted/default, `all` and `none`; nondefault
`IncludeAssets` or `ExcludeAssets` are explicitly rejected in this managed ref/lib
slice. This is a bounded consistency check, not general NuGet evaluation support.

Preparation also diagnoses direct literal version/privacy edits against an old
manifest as `stale-restore`. Its XML inspection and the runner's inline version
guard recognize standard MSBuild XML namespaces. Imported semantics are checked
by the evaluated exporter; raw XML checks do not pretend to evaluate MSBuild.

The five focused regressions in `tests/graph_packages/test_restore_semantics.py`
failed before the fix and passed afterward on native macOS ARM64 (23.7 seconds):
namespaced version change, direct privacy change, imported privacy change,
reference removal and unsupported asset filtering. Failed fresh export leaves no
manifest, and failed direct preparation leaves no replacement plan. After restore,
the changed exact version and private package cases prepare successfully with the
expected App package ownership. The package-free exporter suite (12 tests),
preparation rejection suite (14 tests), and ActionRunner contract/process tests
also passed. Linux acceptance remains the integrated CI gate.

```sh
python3 -m unittest discover -s tests/graph_packages -p test_restore_semantics.py -v
python3 -m unittest discover -s tests/graph -v
python3 -m unittest discover -s tests/graph_execution -p test_prepare_graph.py -v
bash scripts/dotnet.sh run --project tests/ActionRunner.Tests
```
