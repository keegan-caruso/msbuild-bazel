# Action identity: explicit inputs and Python runtime

The Bazel fixture now measures cache invalidation for an imported MSBuild target,
a generated-source data file, declared environment values, restore metadata and
a host-identity input. This is a focused extension of the two-project adapter,
not complete input discovery or a hermetic native toolchain.

## Run

```sh
python3 tools/probe_bazel.py --identity-probe --output artifacts/identity-probe
python3 -m unittest discover -s tests/e2e -v
```

The first successful retained run is `artifacts/identity-3/report.json`, measured
on macOS ARM64 with .NET SDK 10.0.100, MSBuild 18.0.2.52411 and Nix Bazel 8.4.2.
The [planned acceptance matrix](action-identity-plan.md) and black-box assertions
were written before implementation. The source fixture remains unchanged: the
probe adds the imported target and data file only to its copied fixture.

## Measured behavior

The Shared project imports `BuildInputs.targets`. Before compilation, that target
reads `value.txt` and generates a C# constant in obj from the file contents, an
imported property and `SPIKE_INPUT_FLAVOR`. Shared's public value includes that
constant. App consumes the normal Shared assembly through result replay.

After the original six scheduling/cache scenarios, the probe applies:

| Change | Executed actions | Result |
| --- | --- | --- |
| Imported property: import-v1 -> import-v2 | Shared, App | Output includes import-v2 |
| Data file: data-v1 -> data-v2 | Shared, App | Output includes data-v2 |
| Declared environment: env-v1 -> env-v2 | Shared, App | Output includes env-v2 |
| Parent environment: different flavor and PYTHONPATH | None | Output retains env-v2 |
| App project.assets.json: extra ignored metadata field | App | Output unchanged |
| Host identity policy revision: 1 -> 2 | Shared, App | Output unchanged |

The final output is
`shared-v2/data-v2/import-v2/env-v2/app-v2`, through both the DLL and native app
host. The last two cases run after poisoning the parent environment, so freshly
executed actions also retain the declared flavor. The restore perturbation tests
that file bytes participate in the key; it is not a package graph/content change.
The host perturbation is a synthetic policy revision, not an actual OS upgrade.

Execution logs still show native `darwin-sandbox` execution, App-only compilation
inside App actions, and disk-cache hits after cleaning outputs and using a new
output base. Shared's imported target must be declared to App for graph
evaluation, but Shared's data file and C# sources are absent from App's inputs.
Generated C# stays under Shared obj and its compiled results travel in the bundle.

## Runtime inputs and environment

A local repository rule exposes the configured Python executable, its core
library when discoverable, and the standard-library tree. Those files are
explicit action inputs alongside the SDK. The macOS measurement includes 2,649
standard-library files per project action. Bytecode files are included because
Python may read them; `-B` prevents new bytecode writes. Site-packages is excluded.
Python is invoked directly with `-I -S -B`, without a shell launcher, PYTHONPATH,
user-site packages or site customization. Tests inspect the executable arguments,
standard-library inputs and host-identity input in Bazel's execution logs.

`host-identity.json` records platform, machine architecture, Python version,
resolved runtime paths and a policy revision. Preparation regenerates it; users
must reprepare after host changes. This file is a compatibility salt, not proof
that the full host dependency closure has been discovered. The test changes the
policy revision and checks both actions rerun. It does not modify installed
Python or SDK binaries.

The rule accepts explicit `build_environment` entries only under `SPIKE_INPUT_`.
They join fixed PATH and LANG values in the action environment, which Bazel hashes.
Runner-owned workspace, NuGet and .NET settings are still supplied inside each
action. Arbitrary environment forwarding is not supported.

`no-remote` prevents remote execution and remote-cache use while these actions
depend on host state. The execution log confirms `remotable=false` and
`remoteCacheable=false`; local disk-cache recovery remains successful.

## Validation

The complete local command `python3 -m unittest discover -s tests/e2e -v`
passed all ten tests in 152.810 seconds on macOS ARM64. This includes both
Bazel matrices, the original boundary/path controls and public-API replay cases.
Native sandbox tests ran outside the Codex outer restriction. Environment checks
(`bash scripts/check.sh`), Python syntax checks and `git diff --check` also passed.
No Linux workflow was changed or rerun for this milestone.

## Remaining limits and next work

Native libraries outside the declared Python/SDK trees, signing tools and Nix
runtime dependencies are not yet a closed toolchain. Paths and timestamps remain
embedded in diagnostic artifacts; outputs are not proven byte-reproducible.
Tool versions and file inputs do not prove a sandbox declared every absolute
host read. Linux validation is being handled separately by the user.

The subsequent [package experiment](package-input-findings.md) added pinned
build-package contents and package/restore perturbation tests. Native runtime
closure and deterministic output staging remain open before general ProjectGraph
export; see the [current plan](spike-plan.md).
