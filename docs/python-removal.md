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

Steps 1 and 2 landed first. Steps 3 and 4 complete the production switch below.
Python remains available for tests, reference implementations and measurements.

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
Python implementation remains a test oracle. At the step-2 commit it also served
the workflow/reuse paths; step 3 replaces those production paths.

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
Those results describe the original step-2 boundary. The following steps complete
the workflow/reuse/bootstrap migration.


## Steps 3 and 4: production workflow and bootstrap

The production entry points are now:

| Operation | Command |
| --- | --- |
| Fresh graph preparation | `bash scripts/prepare.sh --request request.json` |
| Native Build/Test, reuse and remote cache | `bash scripts/build.sh --bootstrap ...` |
| Linux SDK/Bazel bootstrap | `bash scripts/setup.sh` |
| Pinned Buildifier acquisition | `bash scripts/tooling.sh setup-starlark` |
| Toolchain and Starlark validation | `bash scripts/check.sh` |

See [the workflow guide](native-workflow.md) for restored-source requirements,
test declarations and remote snapshot selection. The controller is compiled .NET;
Bazel continues to execute the existing .NET action and test runners. No production
command invokes a Python interpreter. The old `scripts/setup.py` and
`scripts/setup-starlark.py` are removed. The toolchain container no longer installs
Python; container test harnesses acquire their own test dependencies.

The port covers owned state leases, sealed sandboxed discovery, complete input
snapshots, local reuse, existing-source C# refresh, incremental workspace generation,
project-cache seeds, Build/Test acceptance and final checks before publication.
NuGet's global cache remains read-only to the controller: it stages the selected
restored closure privately. HTTP transport splits preparation into source groups,
metadata and package objects, reconstructs verified package objects from local
NuGet bytes, checks CAS hashes and archive membership, and deduplicates uploads.
Failed tests, altered inputs and invalid packages do not publish snapshots.

State and cache identities deliberately change. Use a new local state directory:
`dotnet-native-workflow-v1` rejects old owned state. Discovery proofs use
`dotnet-native-discovery-v1`, and explicit remote roots use
`dotnet-native-snapshot-v1`. Python-format remote roots cause a miss and fresh
preparation. This migration does not promise cache compatibility across controllers.
At this migration checkpoint, `--trust-system-nix-store` was accepted for CLI
compatibility without retained trust. [Protected toolchain sessions](protected-toolchain-session.md)
subsequently restore opt-in process-local reuse in .NET.

### Current validation

Native macOS ARM64, pinned Nix SDK 10.0.400 and Bazel 8.4.2:

```sh
UseSharedCompilation=false bash scripts/check-dotnet.sh
bash scripts/tooling.sh setup-starlark
bash scripts/check.sh
TMPDIR=/private/tmp python3 -m unittest discover -s tests/dotnet_workflow -v
python3 tests/dotnet_workflow/probe.py \
  --checkout /private/tmp/mr/upstream --packages /private/tmp/mr/p \
  --output /private/tmp/np-serilog4
```

The owned .NET build, warning and format checks passed, as did the 32 fresh
preparation differential tests and five code-style/isolation tests. The 17 new
workflow/component/bootstrap tests cover native-plan parity with the Python
oracle, source refresh/invalidation, NuGet closure isolation, corrupt/missing
packages, safe archive paths, regular-file/link/FIFO boundaries, readonly cleanup,
shell pin parity, production dependency boundaries, installation idempotence and
checksum rejection, stable parallel publication and source/controller separation. Setup acquisition and normal tool validation also ran with
Python/Python3 denied in child PATH. The public `scripts/build.sh --bootstrap`
wrapper also completed a real two-project build under that restriction.

The existing preparation/reuse (118), native-cache (23), MSBuild tool (2), package
staging/analyzer (8), reference import boundary (1), bootstrap (12) and CI dispatch
unit tests (5) also passed locally. CI dispatch tests exercise shell selection only;
they do not launch CI.

The pinned Serilog acceptance removes the producer source, state and Bazel outputs
before fresh remote consumers. Cases cover local unchanged/body reuse, malformed
local proof recovery, fresh remote unchanged/body/API/package/namespace changes,
corrupt preparation and project objects, missing/tampered global packages, leased
source mutation during consumption, and failed approval tests. Production children
run with failing Python/Python3 PATH shims. The harness itself uses Python.

Unchanged consumers compile zero projects; implementation-only edits compile one;
API edits reach the current-runtime approval test and fail as intended. Package
upgrades rebuild both projects. Corrupt objects recover through fresh preparation
or compilation. Missing/tampered packages, changed leased inputs and failed tests
reject without HTTP PUT or new local cache publication. Runtime hashes are checked
against the actual VSTest bundle.

The fourteen-case run (`np-serilog4`) passed and took 18.20 s for the producer,
8.76 s for local unchanged reuse, 12.47 s for a fresh remote unchanged consumer,
and 13.21 s for a fresh remote body edit. Final review then stabilized parallel
publication ordering; the repeat-publication test confirms an identical snapshot
digest and zero uploads over four unchanged repetitions. These are single runs with a 10 ms HTTP delay, not a new
performance baseline or a controlled comparison with raw MSBuild.

### Limits and retained Python

Production is Python-independent in the exercised macOS slice. PATH denial is not
proof of installation on an OS image with Python physically absent. Linux
bootstrap is covered by shell tests with tiny mock tools; actual Linux SDK
installation and the rebuilt container have not been run here. No Linux native
workflow or cross-platform cache qualification is added. No GitHub CI was run.

Python modules under `tools/` are retained only as reference implementations and
experiment harnesses, including the original preparation/reuse/transport modules.
Their old measurements remain labeled historical. Repository tests, benchmarks,
container-test orchestration and development Nix shells may still use Python.
See `tools/PYTHON-REFERENCE.md`; current production callers use the commands above.
