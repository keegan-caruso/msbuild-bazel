# Correctness review of the parallel graph changes

The review concentrated on cache identity, relocation, publication and dependency
consumption. Four actionable defects were reproduced and corrected before the
package milestone was published.

| Defect and consequence | Correction | Regression evidence |
| --- | --- | --- |
| Exporter-overridden absolute request values remained in `entryRequests`, making equivalent relocated graphs differ. | Persist canonical requests, excluding only values always overridden by the exporter; retain semantic custom properties. | Equivalent-request and discovery controls; R01 native macOS and Linux acceptance at `c384671`. |
| Reused MSBuild workers retained a prior CLI home's NuGet configuration paths, changing identities between otherwise equivalent probe runs. | Give preparation children explicit environments and disable MSBuild worker reuse in the probe. | Worker-environment regression plus cache/discovery acceptance at `c384671`. |
| Standard MSBuild XML namespaces bypassed raw PackageReference version checks, allowing a fresh manifest to bless an older restored version. | Read namespace-qualified references and validate evaluated direct references against restored versions before export. | Namespace stale-version and unpinned-version guards reject export and preparation without replacing a warm plan. |
| Changing PrivateAssets after restore could publish App's old transitive package closure. Removing a reference had the same freshness gap. | Compare evaluated direct package sets, exact versions and privacy metadata against restored framework dependencies, including imported metadata; reject unsupported asset filters. | Five focused restore-semantic regressions, four SDK/adapter privacy modes and full warm-plan guards. |

The integrated R02 revision `2407142` passed all 13 full cache tests and seven
PrivateAssets/restore-semantic tests on native macOS ARM64. It includes managed
package upgrades, package-free mutations, deleted-producer relocation, complete
bundle hash/mode comparisons and actual recovered application execution.

The published `9cba8c5` Linux jobs did not start because GitHub reported an account
billing/spending-limit issue. This remains missing platform evidence, not a test
failure or acceptance result. See [package status](graph-package-plan.md).

No additional actionable correctness defect remained in the reviewed R01/R02
scope after those fixes and checks. This does not qualify broader NuGet asset
selection, configured-node extensions, remote caching or full host closure; those
retain separate implementation and acceptance gates. R03 changes are reviewed
and validated separately as they arrive.
