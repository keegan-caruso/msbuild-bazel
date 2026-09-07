# R02 managed packages in generated graphs

This extends the passing package-free graph boundary to a checksum-verified,
managed ref/lib package fixture used by Left. Acquisition and ordinary restore
remain preparation operations. Acceptance requires native Linux and macOS,
package-free regressions, branch upgrade action sets, recovery/relocation and
PrivateAssets comparisons against ordinary SDK behavior.

## Input and action contract

The exporter records package archive/payload inputs named by each node's restored
assets. Preparation verifies those recorded hashes and the archive's SHA-512
against restore metadata, then stages archive-derived files and an installation
marker. A schema-versioned package manifest is generated per configured node.
No package installation metadata or DLL is acquired inside a build action.

Each graph action owns its project's restore/package closure. Dependencies still
arrive as artifact/result bundles. Package payloads are declared action inputs;
the archive and file checks happen before publishing the generated plan. Initial
support is exact inline PackageReference versions and managed ref/lib assets;
unsupported native, RID, generator and build-task payloads must reject explicitly.

Default/omitted, PrivateAssets=all and PrivateAssets=none fixtures compare the
ordinary restore graph, compile visibility and runtime/output copying. A private
package can still affect the SDK's output-copy behavior: privacy does not imply
that no runtime file can reach a consumer. The adapter must match measured SDK
behavior without adding private compile assets to App's restore closure.

## Acceptance

- Left-only package cold build and version upgrade; Shared/Right retain action
  identity, Left/App change, and App prints the selected package value.
- Package-backed recovery after deleting output bases and the producer; verify
  output bytes/permissions and run recovered App.
- Missing package bytes, corrupt bytes with old manifest, stale graph and stale
  restore fail before a replacement plan is published, with explicit diagnostics.
- Full original graph-cache cases remain required; new package coverage does not
  replace the package-free mutation/recovery checks or the explicit-adapter tests.

Evidence is recorded in a linked findings file after each actual run. This plan
alone does not qualify R02 or general NuGet support.

## Initial execution evidence

The first generated package cold build passed on native macOS ARM64 with pinned
Nix SDK 10.0.100/Bazel 8.4.2. Evidence is retained at
`/private/tmp/r02-first-package`: the producer preparation checkout was deleted
after export/staging; all four nodes built under darwin-sandbox; App printed
`shared-v1:left/package-v1|shared-v1:right`. This is only the initial cold case,
not R02 acceptance. Upgrade/recovery/negative/private-asset tests remain required.
