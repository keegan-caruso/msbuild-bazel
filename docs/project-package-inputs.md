# Project-specific NuGet directory inputs

The portable project layout now records each project's package identities from
qualified MSBuild package inputs, including dependency-closure and graph-wide
inputs. It recognizes both workspace `.nuget/packages` and portable `packages`
paths. Discovery validates the complete declaration before compilation. Missing,
extra, escaping and unlocked package declarations fail; older layouts retain the
conservative full package set until regenerated.

With `"package-actions": true`, restore and discovery still receive all locked
packages, while each compile action receives its own typed package-directory
set. Analyzer/build packages and dependency replay inputs remain included. The
compiler resolves and hashes only its prepared payload inside declared trees.

## Qualification

The full local suite passes: 57 workflow tests with one Linux-only skip on macOS,
preparation/style checks and warning-free builds. The native four-project probe
uses Newtonsoft.Json 13.0.1 and PolySharp 1.15.0:

- Native production and producer-deleted fresh remote recovery pass, with exact
  DLL/PDB parity and identical application output.
- Fresh recovery has two extraction cache hits, zero compilations and zero
  extracted package files downloaded (empty Bazel placeholders are expected).
- A source edit in the Newtonsoft consumer compiles one project, reuses
  discovery/extraction and changes application output as expected. It fetches
  24 Newtonsoft files and zero PolySharp files from the unrelated sibling.
- Recorded totals: producer 15.281 s, recovery 3.705 s, source edit 3.474 s. These
  small-fixture, loopback-cache samples are not an Orchard speedup claim.

The exported 202-project Orchard graph has a median package set of 34, minimum
19, maximum 287. Total package references across compile declarations fall from
57,974 to 9,888. Full Orchard execution and timing qualification follows.
