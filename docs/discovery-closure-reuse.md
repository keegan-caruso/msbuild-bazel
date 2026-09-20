# Discovery and binding closure reuse

The package-action path no longer constructs a transitive legacy rule input list
for every project. It stages each project's own sources and restore metadata once;
the union is unchanged and NativePlan still builds each project's actual boundary.
Legacy graph-rule generation retains its transitive lists.

Input validation memoizes existence and containment checks for each declared
root-qualified path within one pass, alongside the existing digest memo. Every occurrence
still validates path syntax, kind restrictions and its expected digest. Independent
graph revalidation and the discovery lease's final byte verification remain.

Project-template generation computes each record's required payload names once,
then unions these sets for each dependency closure. It also computes the graph's
body-source set once. Payload ordering is deliberately unchanged; linked-source
and global-source cases retain byte parity with legacy binding.

This does not reuse evaluation across separate discoveries. Content-only source
edits already use Bazel's project binding actions without discovery. This change
removes repeated work inside a cold discovery without changing that cache boundary.

Validation: 69 applicable workflow tests and 33 preparation tests passed; one
Linux-only workflow test was skipped on macOS. All owned tools build with warnings
as errors. The dedicated paired probe uses unchanged controller inputs, identical
state paths and the same declared Orchard inputs; only the executing preparation
DLL differs. Every discovery and template output file must match byte for byte.

Reproduce with `tests/remote_workers/preparation_reuse_probe.py` and the retained
Orchard `prepare.request.json`, execroot, baseline/candidate preparation DLLs and
pinned dotnet. Native macOS sandbox access is required. Raw evidence is under
`/private/tmp/discovery-reuse-native-measure`.

Paired median: **90.544s → 83.385s (7.9% faster)**.
All four runs match all 1,421 output files. A final root-qualified path-memo
check also matches, at 84.465s. Input validation falls from 8.129s to
4.656s; project templates from 3.464s to 2.552s. Metadata staging remains
9.958s versus 10.246s before. Evaluation/export remains a separate cost.
