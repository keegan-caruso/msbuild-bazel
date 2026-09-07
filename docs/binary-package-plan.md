# Managed binary package boundary

Contract and acceptance scenarios precede implementation. Keep the explicit
Shared -> App graph, net10.0, Release, native sandbox and local disk cache.

`python3 tools/probe_bazel.py --binary-package-probe --output ABSENT_DIRECTORY`
prepares repository-authored packages `RulesMsbuild.Binary` and `RulesMsbuild.Leaf`. Shared
references only RulesMsbuild.Binary; RulesMsbuild.Binary depends on RulesMsbuild.Leaf. Both expose
distinct reference (`ref/net10.0`) and executable (`lib/net10.0`) assemblies.
Methods, not constants, make App execute both package implementations.

Preparation builds package sources with the pinned SDK, creates deterministic
ZIP archives, and records SHA-256 for each archive. These are generated fixture
hashes, not independently checked-in binary pins. Source and toolchain are pinned
by the checkout; no general external-package trust claim is made. Restore occurs
before actions. The existing schema-1 package manifest lists the complete
resolved closure and verifies each payload against its prepared archive. Binary
resolution also requires a `.nupkg.sha512` installation marker: preparation
derives it from the verified archive, checks it against restored `sha512`, and
includes it in the same declared, hash-verified manifest. Ambient `.nupkg.metadata`
and source-feed paths are not copied into the package directory.

The report adds `binaryPackageProbe`, `binaryAssets` per successful case (package
identities from App.deps.json and staged DLL hashes), and per-case compilation
evidence. Existing action requests and bundle schemas remain unchanged unless
an actual handoff failure demonstrates a required extension.

Acceptance:

- Normal traversal and sandboxed App execute both package methods through DLL
  and apphost entry points, after removing preparation workspaces and feeds.
- Each action declares both packages, including reference and runtime DLLs.
  App has no Shared sources; Shared compiles only in its producer action.
- Cold, unchanged, App edit, Shared edit, disk-cache recovery and a new output
  base preserve the existing action-execution matrix.
- Fresh execution with a new output base AND empty cache uses different action
  paths and produces identical consumer bundles, including package outputs.
- A direct package implementation upgrade and a transitive implementation
  upgrade each rebuild both actions and change observed application output.
- App.deps.json contains both resolved identities. Staged package DLLs match
  runtime payload hashes, not reference assembly hashes.
- Missing declarations, corrupt transitive DLL bytes, stale direct restore,
  and an incomplete transitive manifest fail before compilation.
- Removing the declared installation marker fails before compilation.
- Removing the transitive runtime DLL from a copied runnable App output causes
  execution to fail despite the prepared package payload still being available.

Exclude RID-specific/native assets, arbitrary feeds, analyzers, central package
management, version conflict resolution, general publishing and remote caching.
General graph export remains gated on measured acceptance of this slice.
