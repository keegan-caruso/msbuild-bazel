# Selected Spectre acceptance preparation

This gate now has native macOS evidence in [the integration findings](spectre-acceptance-findings.md). It targets the unchanged
Spectre.Console declarations at revision
`2dc90b90add956c2f6777cb659120900ac2eb740`: Console/net10.0,
Ansi/net10.0 and their shared SourceGenerator/netstandard2.0. Framework and package prerequisites are integrated; the findings bound the selected supported scope.

Run from the adapter checkout with pinned SDK 10.0.400 and Bazel available:

```sh
python3 -m unittest discover -s tests/spectre_acceptance -v
python3 tools/probe_spectre_acceptance.py \
  --source /path/to/pinned/spectre.console \
  --packages /path/to/acquired/packages \
  --output /path/to/new/evidence
```

`--cold-only` diagnoses prerequisites and never marks the full gate accepted.
The output directory must be absent. The probe makes standalone Git clones,
preserving Git metadata for ordinary MinVer/SourceLink behavior. It restores
copies, never the input checkout. The package cache seed is optional; restore
can require network. Restore selection and Git-derived version/source metadata
must be reviewed at integration: copying source with no Git metadata or disabling
build-time tools is not an acceptable replacement for unchanged upstream parity.

The independent reflection oracle reads generated Color properties and all
Spinner.Known properties, including actual frames, intervals and Unicode flags.
Both ordinary MSBuild and adapter bundles must yield the same JSON. This is a
selected behavioral oracle, not a claim of full API or upstream test coverage.

| Case | Required executed projects |
| --- | --- |
| Cold | Generator, Ansi, Console |
| Unchanged | None |
| Spinner JSON interval edit | Console |
| Spinner JSON entry added | Console |
| Spinner JSON entry removed | Console |
| Unreferenced JSON file added | None |
| Explicit AdditionalFiles item and file added | Console |
| Added item and file removed back to baseline | None; original action reused |
| Git tag added at HEAD | Generator, Ansi, Console |
| Declared Git shallow input removed after export | Preparation rejects before publication |
| Generator interval emission changed | Generator, Ansi, Console |
| Producer-free relocated recovery | None; three explicit disk cache hits |
| New consumer source after recovery | Console |

The upstream AdditionalFiles declarations name specific files rather than globs.
JSON entry removal uses the unreferenced `dots` spinner, preserving the `Ascii`
spinner required by upstream source. A separate case adds an explicit extra JSON
item/file, then removes both to return to the original baseline. The extra
unreferenced file case checks that a file on disk alone does not become a compiler
input. Baseline declarations are unchanged; the item-add case is an intentional
mutation, not a prerequisite workaround.

Each fresh action must use the native sandbox, and its diagnostic must report
only its own project compilation. Preparation sources are deleted before build.
For recovery, shut down Bazel, delete original generated workspace and output
base, then prepare at a new path using only retained disk cache and freshly copied
inputs. Compare complete bundle bytes/modes with cold; require three disk hits.
Then add consumer source and compile Console using recovered producer bundles.
Record all failures by stage in report.json; never reinterpret a rejected export
as accepted adapter behavior.

Run `--git-only` for the cold/unchanged/tag/missing-input companion gate. It
requires the actual MinVer assembly identity to become 1.2.3 and retains pinned
SourceLink URL parity for every assembly. The full default gate includes those
controls as well. Initial preparation had seven contract tests; integration adds
selected-framework package metadata and actual C# Git discovery rejection tests.
See the findings for commands and measured results.
