# Selected Spectre acceptance preparation

This is a prepared gate, not passing adapter evidence. It targets the unchanged
Spectre.Console declarations at revision
`2dc90b90add956c2f6777cb659120900ac2eb740`: Console/net10.0,
Ansi/net10.0 and their shared SourceGenerator/netstandard2.0. Framework and
package prerequisites must be integrated before the native acceptance run.

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
| Generator interval emission changed | Generator, Ansi, Console |
| Producer-free relocated recovery | None; three explicit disk cache hits |
| New consumer source after recovery | Console |

The upstream AdditionalFiles declarations name specific files rather than globs.
Entry addition/removal above means JSON data entries, not AdditionalFiles item
membership; the extra unreferenced file checks that distinction. Missing explicitly
referenced JSON files and changed item declarations require separate negative/item
membership controls; they are not covered by this initial gate.

Each fresh action must use the native sandbox, and its diagnostic must report
only its own project compilation. Preparation sources are deleted before build.
For recovery, shut down Bazel, delete original generated workspace and output
base, then prepare at a new path using only retained disk cache and freshly copied
inputs. Compare complete bundle bytes/modes with cold; require three disk hits.
Then add consumer source and compile Console using recovered producer bundles.
Record all failures by stage in report.json; never reinterpret a rejected export
as accepted adapter behavior.

Initial preparation validation: seven contract tests passed, covering exact
worksets, repeated dependency compilation rejection, native sandbox enforcement,
explicit recovery evidence and real JSON mutation semantics. No adapter build
was run in this preparation checkpoint. Integration must first resolve selected
restore and Git metadata behavior, then run this gate and record measured limits.
