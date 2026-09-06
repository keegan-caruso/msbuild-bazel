# Deterministic consumer bundles

The first slice of the native-runtime/staging milestone now produces matching
consumer bundles in two independent native macOS ARM64 sandbox executions.
Native runtime closure remains open. Remote execution and remote-cache use remain
disabled.

## Experiment

```sh
python3 tools/probe_bazel.py --staging-probe --output artifacts/staging-after
```

Run inside the pinned Nix development shell. The probe uses a second Bazel output
base and a separate empty disk cache to force both projects to compile again with
identical inputs at new scratch paths. It compares the complete Shared and App
bundle file sets, SHA-256 digests and executable bits. This is separate from the
existing tests that intentionally recover previous results from disk cache.
See the [acceptance contract](staging-plan.md).

The retained before/after reports are `artifacts/staging-before/report.json` and
`artifacts/staging-after/report.json` (ignored local evidence). With SDK 10.0.100,
MSBuild 18.0.2.52411 and Nix Bazel 8.4.2 on macOS ARM64:

| Comparison | Shared differing files | App differing files |
| --- | ---: | ---: |
| Before staging changes | 10 | 7 |
| After staging changes | 0 | 0 |

Before the change, DLLs and portable PDBs differed alongside logs, action reports,
SDK bookkeeping and artifact manifests. The SDK also generated SourceLink data
pointing to the repository enclosing the copied fixture.

## Output boundary

Each action declares two tree outputs: `<target>.bundle` and
`<target>.diagnostics`. Only the bundle is passed to downstream actions. Diagnostics
retain `action.json`, `build.log`, and graph capture output with real paths and
timings. App's graph replay diagnostics remain in its disposable dependency copy.

The comparison covers all six Shared bundle files and all eight App bundle files.
Shared's bundle contains its bin outputs, the reference assembly under
`Shared/obj/Release/net10.0/ref`, the artifact manifest, and normalized replay
results. The earlier whole-obj copy included producer-private generated sources,
editorconfig, absolute file lists and incremental caches. These are no longer
staged. This is an explicit fixture contract, not general MSBuild output discovery.
App's bundle contains its bin outputs and artifact manifest.

The runner sets `Deterministic=true` and maps the current workspace to
`/_/workspace` through `PathMap`. These are evaluated project properties so that
path-dependent global properties do not enter replay identity. Source-control
queries and SourceLink generation are disabled for the copied fixture; its
surrounding checkout is not a declared build input. Compiled binaries are never
rewritten. JSON object keys and the requested-target name set are canonicalized;
result item order is preserved. Staged file modes are normalized to 0644/0755,
retaining executable app hosts, and staging timestamps are set to the Unix epoch.
The equality assertion concerns file bytes and executable bits; it does not claim
Bazel preserves those timestamps when materializing cached outputs.

## Validation

`python3 -m unittest discover -s tests/e2e -v` passed all 12 tests in 256.019
seconds in the pinned Nix shell on macOS ARM64. This includes the new fresh-build
comparison, action identity, package upgrade/rejection cases, native sandbox and
disk-cache behavior, and the original MSBuild boundary/path/replay controls.
`bash scripts/check.sh`, Python syntax checks and `git diff --check` passed.
Native sandbox experiments ran outside the Codex outer filesystem restriction.
No Linux validation was run for this change.

## Limits and next work

The experiment establishes repeatability for this two-project fixture on the same
host/toolchain, across action paths. It does not establish hermeticity, portability
between hosts, or determinism for arbitrary NuGet packages, generated sources,
custom MSBuild targets, signing, or publishing. Native libraries, signing tools
and Nix runtime dependencies outside declared trees still require closure work.
Linux validation remains with the user. General graph export remains deferred.
