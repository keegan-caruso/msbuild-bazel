# Action runner: MSBuild policy and .NET contracts

The runner keeps MSBuild in a child process, but separates invocation construction,
process lifetime, evidence parsing and orchestration. Build settings live in declared
`Action.props` and `Action.targets` files instead of being appended to project XML.

`DirectoryBuildPropsPath` and `DirectoryBuildTargetsPath` are supplied in the child
environment. The wrappers import the fixture's own build files before applying the
action policy. Their paths therefore remain evaluated properties, not additional
global properties in the dependency replay identity. Both policy files are Bazel
inputs. The identity probe changes the props policy and checks both actions rerun.

## File-by-file .NET pass

| File | Change and reason |
| --- | --- |
| `Program.cs` | Keeps only action sequencing; JSON conversion validates the project kind before work starts. |
| `Contracts.cs` | Uses a project enum and typed restore/build-report records instead of string conventions and anonymous report shapes. |
| `JsonFiles.cs` | Separates serialization from contracts; uses streams, frozen options, required constructor parameters, nullable checks and duplicate-property rejection. |
| `BuildInvocation.cs` | Owns arguments and action-specific environment, including the policy import paths. |
| `ProcessRunner.cs` | Drains stdout/stderr concurrently, returns an explicit result and handles timeout and caller cancellation separately. |
| `BuildEvidence.cs` | Uses generated, culture-invariant regexes and verifies project/replay evidence independently of process execution. |
| `Msbuild.cs` | Orchestrates invocation, diagnostics and result validation. |
| `Workspace.cs` | Stages inputs without rewriting build XML. |
| `PackageInputs.cs` | Reads typed restore metadata and uses ordinal, case-insensitive package identity comparisons. |
| `NativeRuntimeInputs.cs` | Validates the native declaration independently of NuGet staging. |
| `Files.cs` | Hashes payload streams and uses the directory timestamp API for directories. Stream length follows Bazel input symlinks. |
| `Bundles.cs` | Uses the typed project identity and separates result canonicalization from artifact export. |

The JSON wire names and bundle schema remain compatible, apart from the new
required `build_props`/`build_targets` action inputs and explicit rejection of
malformed requests. The stderr stream is retained after stdout in `build.log`;
cross-stream chronology is not guaranteed. No MSBuild API hosting, SDK upgrade,
NuGet package dependency or Python harness migration is introduced.

## Validation

Inside `nix develop`:

```sh
bash scripts/dotnet.sh run --project tests/ActionRunner.Tests -c Release
python3 tools/probe_bazel.py --staging-probe --output artifacts/build-policy-1
python3 tools/probe_bazel.py --package-probe --output artifacts/build-policy-packages-1
SPIKE_NATIVE_RUNTIME_TEST=1 python3 -m unittest discover -s tests/e2e -v
```

The focused console tests use no test-framework package. The e2e harness invokes
them on both Linux CI workflows. They cover missing/null/duplicate/invalid request
fields, large output pipes, nonzero exits, timeout, cancellation, CRLF evidence,
rejection of repeated dependency compilation and symlinked payload verification.

The full opt-in e2e suite passed all 14 tests in 309.931 seconds on macOS ARM64.
The focused tests and retained package probe also passed. Package
data/target upgrades rebuilt both projects, disk-cache controls recovered both
bundles, and missing/corrupt/stale package controls were rejected before compilation.

The retained staging run compares equal consumer bundle contents and modes across
fresh macOS sandbox executions with empty caches. The policy mutation is included
in the action-identity matrix. Package validation also fixes a regression found
in commit `1640934`: `FileInfo.Length` measured a Bazel symlink instead of the
payload, rejecting valid package files. Payload length and hash now come from the
same opened stream, with a focused regression test.

Native host dependencies, remote cache correctness and general project graph
export retain the limitations described in the earlier findings.
