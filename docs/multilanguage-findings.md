# Existing-rule multi-language harness: first R12 slice

The generated package-free .NET diamond now composes with Python and TypeScript
under one Bazel `py_test`. This is a local harness slice, not Aspire acceptance or
completion of the `languages` roadmap node.

The fixture pins rules_python 1.7.0, aspect_rules_js 3.4.1, aspect_rules_ts 3.10.1,
rules_nodejs 6.7.3, Python 3.11.13, Node 22.20.0 and TypeScript 5.6.2. Python and
TypeScript actions use upstream rules; no custom language compiler rule is added.
The adapter still compiles .NET with SDK 10.0.100/MSBuild. The root scaffold module
is unchanged: the probe adds these dependencies only to its generated workspace.

Upstream configuration references: [Python toolchains](https://github.com/bazel-contrib/rules_python/blob/main/docs/toolchains.md),
[TypeScript module extension](https://github.com/aspect-build/rules_ts/blob/v3.10.1/ts/extensions.bzl),
and [Node toolchain extension](https://github.com/bazel-contrib/rules_nodejs/blob/v6.7.3/nodejs/extensions.bzl).

## Measured native macOS result

On macOS ARM64, with the repository's pinned Nix SDK and Bazel 8.4.2, ran:

```sh
python3 tools/probe_multilanguage.py --output /private/tmp/msbuild-polyglot-third
```

Exit 0. The final acceptance command
`python3 -m unittest discover -s tests/multilanguage -v` also passed
(1 test, 70.903 seconds), with retained evidence under
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/msbuild-multilanguage-jqtj0_o2/probe`.
The ordinary MSBuild baseline and original four-action graph acceptance
pass before harness composition. The preparation checkout is then absent.
`//:polyglot_test` resolves declared runfiles, invokes already-built Python,
TypeScript and .NET programs, and checks their exact output. It does not restore
or build on launch. Cold compilation uses `darwin-sandbox` for four MSBuild
actions and the upstream TypeScript compiler action.

| Case | Observed compilation |
| --- | --- |
| Cold | Four .NET projects and TypeScript |
| Unchanged | No new actions; cached test |
| Python source edit | Test reruns; no .NET or TypeScript compilation |
| TypeScript source edit | TypeScript recompiles; .NET reused |
| App source edit | App recompiles; dependencies and TypeScript reused |
| Deleted output base | Four .NET disk-cache hits; no .NET or TypeScript compilation |

Each edit also updates the independent expected-output assertion. Edits are
sequential and target the prepared workspace; .NET discovery/re-export controls
are measured in the separate R01 tracks. Python source consumption follows
upstream rules_python behavior and does not imply a Python compiler action.

Raw execution JSON, Bazel test logs, generated module lock and
`multilanguage-report.json` remain under the output directory. The scoped
acceptance command is `python3 -m unittest discover -s tests/multilanguage -v`.
Initial runs exposed a missing direct executable prerequisite and a `./`
runfiles-path normalization error; both were fixed before the passing run.

## Remaining gates

Linux harness acceptance, relocation,
missing-runfile rejection and Aspire service composition remain open. Dependency
fetches occur before actions and need network access; execution evidence is local
and does not establish full host closure or cross-worker portability. These
correctness runs overlap other track validation and are not performance evidence.
