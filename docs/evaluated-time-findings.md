# Evaluated-import time diagnostics (RUL-5)

The time-input diagnostic tool can now consume the existing GraphExport request
and its output. It scans recorded project/import XML from the selected configured
graph, including property-selected, SDK and package imports. Findings retain XML
location, conditions and evaluation/target context and add configured-node owners.
Application source remains outside this scan.

```sh
python3 tools/check_msbuild_time.py --graph-request /path/to/export-request.json \
  --output /tmp/time-diagnostics.json
```

The request must describe the same SDK and entry-point/global-property selection
as its output. Root mappings follow the exporter (workspace, packages, SDK,
adapter and Nix SDK imports). Recorded hashes are verified before scanning, with
the exporter's normalized text convention for import files. The parser consumes
the exact verified byte buffers, so a second file read cannot substitute different
content. Missing, changed, escaping and conflicting records fail with exit 2.
This verifies each listed XML snapshot; it is not an atomic filesystem snapshot.

Graph mode does not recursively follow literal imports. Doing so would scan
inactive imports and could read files outside the recorded graph. The standalone
file mode retains its original conservative literal-import behavior. Both modes
retain potential findings inside XML conditions without claiming those expressions
executed for every owning configuration.

## Measured evidence

SDK 10.0.400, native macOS ARM64:

```sh
python3 -m unittest discover -s tests/msbuild_time -v
python3 tools/probe_evaluated_time.py --output /tmp/evaluated-time-probe
```

Twenty-two diagnostic tests pass. They include the original 12 file-scan cases,
changed/missing/hash-conflicting XML, path/symlink rejection, UTF-16 normalized
hashes, package/nonstandard-extension imports, schema/configuration/SDK mismatch,
and scanning verified bytes despite a subsequent file mutation.

The actual SDK/GraphExport probe passes seven cases at
`/private/tmp/rul5-evaluated-time-2/report.json`:

| Case | Observation |
| --- | --- |
| Flavor A | Property-selected A.props clock expression and actual SDK imports are inventoried; application source and inactive imports are excluded |
| Flavor B | B.props replaces A.props; its target-time item timestamp expression is attributed to the selected configured node |
| New optional file, old export | Previously recorded bytes still verify; the old inventory does not contain the new import and remains ineligible for reuse |
| New optional file, fresh export | MSBuild records the newly present import and the scanner diagnoses its timestamp expression |
| Timestamp-only touch | Content inventory still verifies; this does not establish timestamp eligibility |
| Changed selected import | Rejected as stale XML before scanning |
| Missing selected import | Rejected before scanning |

The probe restores and evaluates an authored net10.0 project; it does not compile
or run Bazel actions. An initial attempt stopped because an empty package-free
restore did not create the package-root directory; the probe now creates it
explicitly before export. No production code was changed to bypass validation.

## Remaining RUL-5 boundary

`inventoryVerified` means listed XML bytes match their recorded hashes.
`reuseEnabled` stays false and `eligibility` stays `not-established`.
Membership/glob changes and optional imports require fresh export or a separately
enforced read-domain identity. Generated NuGet import wrappers are not explicit
import records in the current exporter; their resolved package imports are
inventoried, but the diagnostic reports that wrapper coverage gap.

This scanner neither traces nor constrains task/process/environment/external
filesystem reads. It does not enforce timestamp staging, carry a new build-context
property, integrate the older content-identity prototype, or enable production
preparation reuse. Those are the remaining implementation gates for RUL-5/RUL-6.
A clean XML report cannot substitute for them. The existing
[deterministic CI contract](deterministic-ci-contract.md) still applies.

The next design uses [MSBuild filesystem observation hooks](preparation-observation-design.md)
to record and recheck negative existence probes, enumeration results and content
reads. This supersedes conservative tree hashing as the preferred starting
approach; recorder coverage and timestamp eligibility still require experiments.
