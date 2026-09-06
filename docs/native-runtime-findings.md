# Nix native runtime inputs

The first native-runtime slice declares the transitive Nix reference closures
of the selected .NET SDK and Python runtime to both Bazel project actions.
It is opt-in and retains the host salt and `no-remote` execution policy.
See the [acceptance plan](native-runtime-plan.md).

## Run

Inside `nix develop`:

```sh
python3 tools/probe_bazel.py --native-runtime-probe --output artifacts/native-runtime-3
SPIKE_NATIVE_RUNTIME_TEST=1 python3 -m unittest discover -s tests/e2e -v
```

The Nix CI workflow enables this test on Ubuntu 22.04. The setup workflow keeps
its downloaded SDK and system Python path and skips this Nix-specific test.
Preparation uses `nix-store` from PATH, falling back to the standard Nix profile.
Non-Nix runtime roots are rejected. Store dependencies can be directories or
single files; both are included.

## macOS ARM64 evidence

The retained `artifacts/native-runtime-3/report.json` records SDK 10.0.100 and
28 Nix store paths containing 13,620 declared files per action. This includes
ICU, OpenSSL, libffi, compression libraries, sigtool, linker tools and Nix's
apphost signing targets, alongside the SDK and Python. These are conservative
reference dependencies, not a measurement of which files were actually read.

| Case | Executed projects | Result |
| --- | --- | --- |
| Cold | Shared, App | DLL and apphost produce shared-v1/app-v1 |
| Unchanged | None | Same output |
| App edit | App | shared-v1/app-v2 |
| Shared edit | Shared, App | shared-v2/app-v2 |
| Clean outputs, retain disk cache | None | Both bundles restored |
| New output base, same disk cache | None | Both bundles restored |
| Remove native closure declaration | Shared fails | Rejected before compilation |

Cold actions use `darwin-sandbox`. The probe verifies every inventoried file in
both cold execution input logs. Its negative control leaves the Nix store intact
but supplies an empty native filegroup; the runner rejects the mismatch with the
manifest before starting MSBuild. The original undeclared-relative-input sandbox
control also fails as expected. Installed store files are never modified.

## Local regression validation

On macOS ARM64, `SPIKE_NATIVE_RUNTIME_TEST=1 python3 -m unittest discover -s tests/e2e -v`
passed all 13 tests in 314.022 seconds. This includes identity, package, staging,
scheduling/cache, same-path boundary, relocation and public-API replay cases.
`bash scripts/check.sh`, Python syntax checks and `git diff --check` also passed.
Native sandbox execution ran outside the outer agent restriction.

## Linux validation

At commit `ba80e29`, the [Nix workflow](https://github.com/keegan-caruso/msbuild-bazel/actions/runs/34005560602)
passed all 13 tests in 695.839 seconds on Ubuntu 22.04. The [setup workflow](https://github.com/keegan-caruso/msbuild-bazel/actions/runs/34005560579)
passed 12 tests with the Nix-only test skipped (735.243 seconds for the suite).

The subsequent [.NET runner change](dotnet-runner-findings.md) removes Python
from actions and changes the closure roots to the SDK alone. The SDK/Python
counts above describe the original experiment, not the smaller current closure.

## Boundary and remaining work

Nix references close a larger part of action identity, including external native
libraries and signing tools. Bazel hashes declared file payloads; this experiment
does not mutate installed native binaries or claim a measured library upgrade.
Absolute store paths remain in use. The manifest is regenerated on preparation,
and its contents are declared inputs too.

Host OS libraries, macOS dyld shared-cache/framework contents and `/usr/bin`
programs remain outside this manifest. Nix reference traversal does not discover
arbitrary dynamically computed host paths, and Darwin sandbox success does not
prove all host reads were declared. Closure payloads are not relocated. Remote
execution/cache correctness, arbitrary package runtime assets and general input
discovery remain unproven. The [runtime integrity extension](native-runtime-integrity-findings.md)
adds a copied-library change/rejection control and loader diagnostics. It does
not redirect actual library loading or establish full closure.
