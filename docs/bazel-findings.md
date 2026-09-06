# Two-project Bazel action findings

The fixture now builds through two custom Bazel actions with MSBuild dependency
result replay. On macOS ARM64, actual `darwin-sandbox` execution preserves the
Shared -> App boundary and Bazel's local disk cache reuses both bundles.

## Run and evidence

Use the pinned development environment:

```sh
python3 tools/probe_bazel.py --output artifacts/bazel-probe
python3 -m unittest discover -s tests/e2e -v
```

The first successful retained probe is `artifacts/bazel-4/report.json`. It used
.NET SDK 10.0.100, MSBuild 18.0.2.52411 and Nix Bazel 8.4.2 on macOS ARM64.
Commands, MSBuild logs, action reports, Bazel JSON execution logs and runtime
output are retained under the selected output directory. The source fixture is
never built in place. The final harness also builds a normal traversal baseline
and compares its output with the cold Bazel result.

The [process contract](bazel-interface.md), black-box test and expected failing
run were established before the runner. The initial test failed because
`tools/probe_bazel.py` did not exist. The implementation consists of the explicit
rule in `bazel/msbuild.bzl`, the action runner in `tools/bazel_action.py` and the
preparation/measurement harness in `tools/probe_bazel.py`. The harness generates
an isolated Bazel workspace with `//:shared` and `//:app`; the repository root's
`//:repo_setup` remains a setup check.

| Case | MSBuild actions executed | Disk-cache hits | App output |
| --- | --- | --- | --- |
| Cold | Shared, App | None | `shared-v1/app-v1` |
| Unchanged | None | No spawn required | `shared-v1/app-v1` |
| App edit | App | Shared already up to date | `shared-v1/app-v2` |
| Shared edit | Shared, App | None | `shared-v2/app-v2` |
| `bazel clean`, retain disk cache | None | Shared, App | `shared-v2/app-v2` |
| New Bazel output base, same disk cache | None | Shared, App | `shared-v2/app-v2` |

Execution logs distinguish a spawn's `cacheHit` flag and runner from merely
finding old log text inside a restored bundle. The cold build reports two
`darwin-sandbox` executions; App-only edits report one. Cache recovery reports
`disk cache hit` for both actions. The unchanged build records no project spawn.

## Action boundary

Shared runs a graph build of `Shared.csproj` only, explicitly requesting the six
targets established by the replay experiment. Its compile marker is only Shared.
App stages Shared's bundle at a different scratch path, then performs its own
graph build with strict project isolation. Its marker is only App and the replay
plugin reports a Shared hit. Neither action uses `BuildProjectReferences=false`.

Restore and plugin compilation happen before the Bazel builds. Each project's
restore state is normalized to workspace/SDK tokens, passed as a declared file,
and expanded inside the action. The original restore workspace is deleted
before the cold build. This fixture has no application PackageReferences;
Traversal is needed only by preparation/the baseline and is not copied into the
compile action. General package contents and build targets need a larger input
contract before they can be supported.

The SDK file tree, replay assembly, runner, source files, project files, common
imports, global.json, NuGet.Config and normalized restore state are declared
inputs. Shared has no App inputs. App receives Shared's project file for graph
evaluation but no Shared C# source files. The test checks both the execution-log
input lists and the action's scratch workspace. Output copies preserve executable permissions, and every cache scenario runs
both `dotnet App.dll` and the generated native app host. Dependency artifacts are
hash-validated before staging and again by the replay plugin before a hit.

An undeclared relative input exists in the copied checkout but is omitted from
the action inputs. Reading it inside the sandbox fails with `FileNotFoundError`;
the harness requires that diagnostic, not merely an arbitrary failed build.

## Sandbox environment and limits

The harness requires `darwin-sandbox` on macOS or `linux-sandbox` on Linux. It does
not silently substitute `processwrapper-sandbox` or local execution. The Codex
outer restriction prevented Bazel from registering its native macOS sandbox;
the measured run used the authorized execution outside that outer restriction.
Ordinary local development must likewise permit the OS sandbox facility. Linux
execution has not been measured locally; CI remains necessary.

Nix's Bazel launcher obtains its Java runtime from its system bazelrc. The
harness preserves that system configuration and disables home/workspace rc files.
In that initial implementation, action environment variables and the host Python
path were explicit. The entire
SDK file tree participates in Bazel's action inputs, but the host Python standard
library, shell, native libraries, macOS signing tools and Nix runtime closure
were not declared as complete toolchains. The subsequent
[identity experiment](action-identity-findings.md) declares Python runtime files,
removes the shell launcher, and tests more build inputs; native closure remains
incomplete. A native sandbox plus declared relative inputs
does not prove every absolute host read was declared. Actions request network
blocking; this is not a general file-access or network audit.

Artifacts and retained logs may embed original scratch paths. Outputs are not
claimed byte-reproducible across uncached runs. The fresh-output-base case reuses
cached outputs without rerunning either action; it does not prove replay into a
new machine, OS, checkout or SDK location. No remote cache or remote execution
has been tested. These are local scheduling/cache findings for this fixture.

## Validation

On 2026-09-05 with the pinned Nix tools:

- The full nine-test e2e run passed all build assertions and the eight existing
  tests; its new Bazel test initially errored during deletion of read-only Bazel
  output directories. Cleanup now grants write permission only to directories
  within the test workspace, without following SDK/execroot symlinks.
- After that fix and executable-permission preservation, the targeted command
  `python3 -m unittest discover -s tests/e2e -p test_bazel_boundary.py -v` passed
  in 36.940 seconds, including native-app-host execution in all six scenarios.
- `bash scripts/check.sh`, Python syntax compilation of the new runner/probe/test,
  and `git diff --check` passed.

Native macOS sandbox tests were run outside the Codex outer restriction. No
Linux or remote-execution validation is included in these results.

## Subsequent work and remaining scope

[Identity tests](action-identity-findings.md) subsequently added custom imports,
data, environment and Python runtime inputs. [Package tests](package-input-findings.md)
added pinned build assets and upgrade/rejection cases. Native runtime closure,
deterministic staging and Linux native-sandbox evidence remain open. General
publishing, multi-targeting, arbitrary package tasks and remote execution remain
deferred. See the [current plan](spike-plan.md).
