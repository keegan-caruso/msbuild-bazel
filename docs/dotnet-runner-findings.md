# .NET project action runner

Bazel now launches `dotnet runner/ActionRunner.dll --request ...` using the same
SDK that runs MSBuild. Preparation builds the console app and declares its DLL,
deps.json and runtimeconfig.json as action inputs. The app has no package
references or additional runtime to bootstrap.

Python remains in the experiment driver, restore/package preparation and tests.
The Python action script and runtime repository are removed. The action host salt
no longer includes Python paths or versions, and the opt-in Nix closure starts
from .NET alone. Fixed environment values, native sandboxing and `no-remote`
remain in effect.

The runner is split into typed request/manifest contracts, input validation,
workspace preparation, MSBuild process execution and bundle handling. It preserves
package hash checks, dependency replay, compilation assertions, diagnostic output,
compiler path mapping, canonical result metadata and output modes/timestamps.
It locates the loaded SDK host using `Environment.ProcessPath`, so SDK tokens
in restore metadata agree with MSBuild across sandbox symlinks.

## Acceptance

See the [migration plan](dotnet-runner-plan.md). Run inside `nix develop`:

```sh
python3 tools/probe_bazel.py --native-runtime-probe --output artifacts/dotnet-runner-1
SPIKE_NATIVE_RUNTIME_TEST=1 python3 -m unittest discover -s tests/e2e -v
```

Tests inspect each cold action's executable and support files and reject Python
runtime/standard-library declarations. Existing identity, package, staging and
cache tests exercise the replacement through the same fixture behavior.

## Retained macOS result

`artifacts/dotnet-runner-1/report.json` passed the native sandbox matrix: cold
Shared/App execution, unchanged reuse, App-only and Shared edits, cleared-output
disk-cache recovery and a fresh output base. DLL and native apphost outputs match.
The incomplete-native-declaration and undeclared-relative-input controls both
failed as expected before compilation.

The native inventory shrank from 28 store paths / 13,620 files in the Python
experiment to 19 paths / 6,009 files. No Python store roots remain in that
inventory. The declared SDK host launches the runner directly. The runtime
configuration and dependency JSON are staged alongside its DLL.

## Subsequent review changes

The [runner refactor](action-runner-refactor.md) separates process execution from
build evidence, moves policy to declared MSBuild imports and makes a file-by-file
.NET contract pass. It also fixes the symlink-length package validation regression
found by CI on this initial runner commit. The initial native probe above did not
exercise package payloads; see the refactor for that separate validation.

## Limits

This removes Python from build actions only. It does not remove .NET's native
libraries or undeclared host OS dependencies, relocate Nix store paths, or prove
remote caching. It retains the explicit Shared/App adapter and fixed Release,
net10.0 scope.
