# Production Python removal

The migration retains Python for repository tests, acceptance probes and benchmarks.
Production preparation, Build/Test orchestration, reuse, transport and bootstrap
move to .NET with a minimal shell SDK bootstrap. The existing MSBuild/Bazel
contracts and project-owned target frameworks remain authoritative.

## Sequence

1. Separate production helpers from experimental harness imports.
2. Port fresh graph preparation and compare outputs/rejections with Python controls.
3. Port Build/Test orchestration, local preparation reuse and remote snapshots.
4. Remove Python from setup and normal tooling; qualify a Python-free environment.

Each step is committed separately after its relevant checks. Until the final gate,
Python remains required by production paths that have not yet migrated.

## Step 1: production dependency boundary

Moved Bazel execution-record parsing and native fixture eligibility into production
modules. Existing probes import those helpers. The native workflow no longer imports
probe modules or their test fixtures.

Validation: `python3 -m unittest discover -s tests/production_boundary -v` and
`TMPDIR=/private/tmp python3 -m unittest discover -s tests/native_cache -v`: all 24 tests passed on native macOS ARM64. The HTTP tests required local socket access outside the execution sandbox; the canonical temporary path avoids the existing `/var` versus `/private/var` fixture mismatch.
This is dependency cleanup, not yet removal of the Python runtime.

## Step 2: .NET fresh preparation

`tools/Preparation` is a standalone .NET 10 executable using only
`System.Text.Json` for JSON. It does not import or invoke Python. The existing
Python implementation remains the test oracle and the controller used by the
not-yet-migrated workflow/reuse paths. This commit does not switch those paths.

The production entry point is:

```sh
bash scripts/prepare.sh --request /absolute/path/to/preparation-request.json
```

The wrapper builds the tool with the repository SDK wrapper. For repeated calls,
invoke the built `Preparation.dll` using the selected .NET host with arguments
`prepare --request <file>`. Restore the subject and export its graph first using
the existing .NET GraphExport executable. The preparation request is:

```json
{
  "schemaVersion": 1,
  "repository": "/absolute/path/to/rules_msbuild",
  "workspace": "/absolute/path/to/restored-source",
  "manifest": "/absolute/path/to/exported-graph.json",
  "output": "/absolute/path/to/new-generated-workspace",
  "sdkRoot": "/absolute/path/to/dotnet",
  "sdkVersion": "10.0.400"
}
```

`output` must not exist and must be outside `workspace`. Optional fields are
`toolTargetFramework` (`net10.0` or `net11.0`), `msbuildEngineRoot`,
`compileBoundary` (default false), and `tests` (the existing explicit
`node`/`data`/`expectedTests` declaration array). Unknown fields and schema versions
are rejected. SDK defaults retain `RULES_MSBUILD_DOTNET_ROOT`, `.tools/dotnet`, and
`global.json`; they do not override project target frameworks. Child tools receive
explicit SDK/engine/host environment bindings. This entry point supports fresh
preparation only, with no leased or prebuilt-tool bypass.

The port covers graph/configuration/output validation, iterative dependency
closures, framework edge selections, input hash verification, graph re-evaluation,
package archive/content verification and staging, runner/import publication,
restore relocation, and BUILD/MODULE/test-data generation. A shared `flock` lease
serializes tool builds with the Python controller. The completed staging directory
is renamed into place only after validation; failures do not publish an output.
This fresh path does not claim the sealed-discovery or preparation-reuse contract.

JSON formatting and Starlark formatting may differ from Python. Tests compare
parsed declarations/manifests and exact payload bytes. Restore JSON embedded in
receipts is compared structurally; NuGet-generated XML retains its UTF-8 BOM and
normalized newline behavior. Package files retain archive order and byte content.
The C# host identity deliberately uses `policyRevision: 2` and
`controller: dotnet-preparation-v1`; existing Python-produced action identities are
not silently treated as identical. No persisted preparation-cache compatibility is
claimed by this step.

### Measured validation

On native macOS ARM64 with official .NET SDK 10.0.400 and Bazel 8.4.2:

```sh
UseSharedCompilation=false bash scripts/check-dotnet.sh
bash scripts/check.sh
TMPDIR=/private/tmp python3 -m unittest discover -s tests/dotnet_preparation -v
RULES_MSBUILD_DOTNET_ROOT="$PWD/.tools/dotnet" UseSharedCompilation=false TMPDIR=/private/tmp \
  python3 tests/dotnet_preparation/probe.py --output /private/tmp/dp4 --bazel
RULES_MSBUILD_DOTNET_ROOT="$PWD/.tools/dotnet" UseSharedCompilation=false TMPDIR=/private/tmp \
  python3 tests/dotnet_preparation/probe.py --output /private/tmp/dpp --bazel --packages
```

Use new, short output paths; the existing macOS .NET pipe-path limit also applies
to these generated Bazel workspaces. The SDK download was verified against
Microsoft's release-metadata SHA-512; Bazel was verified against its release SHA-256.
Neither downloaded tool is tracked.

The 32 differential tests passed: schema/configuration/path/output rejection,
stale input diagnostics, all supported BOM encodings, selected framework edges,
a 1,000-node chain, canonical JSON encoding, package-byte parity and
mutation/corruption/missing-payload rejection, and compile-boundary rejection of
custom tasks, targets, content, analyzer references and property functions. The separate production import
boundary test passed. The owned-.NET build/format/warning checks and five
code-style/isolation tests passed. Scaffold validation and formatting/lint of all 12 tracked Starlark files passed.

Both real acceptance runs passed preparation parity, exact source/runner/test-data
parity, parsed restore/package manifest parity, ordinary MSBuild output parity,
two fresh native sandbox project executions, and rejection of a new globbed source
against the previous graph with no failed output publication. Preparation itself
ran with an empty PATH directory, exercising only explicit .NET executable paths.
The managed-package case created a local package, restored it privately, verified
and staged its archive, and compiled and ran its consumer. Test declarations/data
were compared; these probes do not execute the synthetic declared test name.

Reports are retained locally in `/private/tmp/dp4/report.json` and
`/private/tmp/dpp/report.json`. The acceptance scope is these native macOS cases,
not Linux/Nix, the broader upstream project portfolio, alternate tool frameworks,
remote-cache qualification, or installation on a machine without Python.
Python remains necessary for the original workflow/reuse/bootstrap paths; those
steps are deferred at the user's requested second-commit boundary.
