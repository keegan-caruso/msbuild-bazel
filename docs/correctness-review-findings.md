# Correctness review of the parallel graph changes

The review concentrated on cache identity, relocation, publication and dependency
consumption. Four actionable defects were reproduced and corrected before the
package milestone was first published. A subsequent partial-restore control found
a fifth issue, described below.

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

Those checks did not cover restoring only a dependency after changing its
package metadata. That gap is corrected by the consumer snapshot checks below. This does not qualify broader NuGet asset
selection, configured-node extensions, remote caching or full host closure; those
retain separate implementation and acceptance gates. R03 changes are reviewed
and validated separately as they arrive.

## Partial consumer restore freshness

At `737e29f`, restoring the whole package diamond, changing Left to
`PrivateAssets=all`, and then restoring only Left still allowed fresh export and
preparation to publish App's old public package closure. App ran successfully
using those stale package inputs. A full restore instead removed both packages
from App and reproduced the ordinary missing-runtime-dependency result.
Evidence: `/private/tmp/restore-closure-repro/report.json`.

The fix must compare the dependency request semantics saved in each consumer's
restore graph with current evaluated dependencies. Comparing only each node's
own direct references is insufficient. Comparing all resolved transitive versions
for equality would also be incorrect because NuGet resolution may legitimately
select different versions. The fix now validates those saved requests, project edges and successful restore
completion. Twelve focused regressions pass, including a natural failed-restore
case and a valid consumer/dependency version-resolution difference. Full native
integration checks are recorded in [consumer restore findings](consumer-restore-findings.md).
