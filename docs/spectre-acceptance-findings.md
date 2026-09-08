# Selected Spectre integration findings

The unchanged Spectre.Console baseline at revision
`2dc90b90add956c2f6777cb659120900ac2eb740` now passes selected native macOS ARM64
adapter acceptance with SDK 10.0.400 and Bazel 8.4.2. Console and Ansi retain
net10.0, and their shared source generator retains netstandard2.0. The ordinary
baseline and cold adapter use the original project declarations and build-time
tools; MinVer and SourceLink are active. No GitHub CI or remote worker was used.

## Command and evidence

```sh
python3 tools/probe_spectre_acceptance.py \
  --source /path/to/pinned/spectre.console \
  --packages /path/to/acquired/packages \
  --output /path/to/new/evidence
```

The full eleven-case run is retained at
`/private/tmp/spectre-integrated-full-2/report.json` (2026-09-07). It used
`/private/tmp/run-sdk-latest`, the original shallow pinned source and the acquired
package cache. These paths identify local evidence, not portable build inputs.
The subsequently added Git companion passed at
`/private/tmp/spectre-integrated-git-2/report.json` using the same command plus
`--git-only`. It covers cold, unchanged, a new `1.2.3` tag at HEAD, and missing
declared metadata. The tag causes all three native actions to execute; assembly
version becomes `1.0.0.0`, file version `1.2.3.0`, and informational version
`1.2.3+` the pinned revision, exactly matching ordinary MinVer policy. Generated
Spinner/Color behavior and SourceLink URLs remain unchanged. Removing the declared
`.git/shallow` file after export fails preparation with `missing-input` and leaves
no published workspace. The default full gate now includes these companion cases.

| Case | Fresh native project actions | Result |
| --- | --- | --- |
| Cold | Generator, Ansi, Console | Ordinary generated behavior and version/SourceLink URL parity |
| Unchanged | None | Original actions reused |
| JSON interval edit | Console | Default interval changes from 100 to 107 ms |
| JSON spinner entry added | Console | Generated AcceptanceProbe spinner appears |
| JSON spinner entry removed | Console | Generated Dots spinner disappears |
| Unreferenced JSON added | None | Explicit AdditionalFiles membership retained |
| Explicit AdditionalFiles item/file added | Console | New item discovered and compiled |
| Added item/file removed | None | Original action recovered from cache |
| Generator emitter edited | Generator, Ansi, Console | Generated intervals increase by 1 ms |
| Producer-free relocated recovery | None | Three explicit disk hits; full bundle bytes and modes match cold |
| Consumer source after recovery | Console | Actual consumer compilation with recovered dependencies |

Every executed action used `darwin-sandbox`; diagnostics report exactly its own
project compilation. Preparation source copies were deleted before action
execution. Recovery deleted original generated workspace and output base after
Bazel shutdown, prepared at new paths, and used only the retained disk cache for
producer outputs. This proves local same-host recovery, not independent-worker or
remote-cache correctness.

The reflection oracle compares every generated spinner's frames, interval and
Unicode flag, plus generated Color property values. Cold has 90 spinners and 291
colors. It also reads all three assemblies' versions and embedded portable-PDB
SourceLink URLs. Assembly/file versions are `0.0.0.0`; informational version is
`0.0.0-alpha.0+2dc90b90add956c2f6777cb659120900ac2eb740`. Each has a nonempty GitHub
mapping at that revision, matching ordinary MSBuild. Compiler paths are deliberately
mapped in adapter outputs; ordinary and adapter PDB bytes are not claimed equal.

## Integration fixes

SDK negotiation emits `UndefineProperties` for the single-target producer.
Copying only `SetTargetFramework` inherited net10.0 into the generator and caused
NETSDK1005; preserving SDK global-property removal fixes export. The action graph
also preserves the absence of a framework global for an implicit producer,
preventing strict dependency replay from rejecting mismatched global properties.
Every real generator results payload is asserted to identify netstandard2.0.

Package validation/staging now selects the node's framework consistently across
the exporter, Python preparation and action runner. It does not merge PrivateAssets
metadata across restore frameworks or validate unrelated targets' asset roles.
A regression changes JSON framework order and confirms that an unselected target
cannot overwrite the selected target's privacy metadata. Selected package archives
and extracted payloads remain subject to the existing content-hash/pin checks;
full restore metadata is retained for SDK evaluation and stale-restore validation.

Git-dependent build inputs are declared for standalone source snapshots: HEAD,
index, origin/config, packed and loose refs, tags, shallow state, objects and the
selected Git info files. Source acquisition preserves the upstream remote rather
than leaving a local clone path as origin. A fresh index from `git read-tree HEAD`
removes checkout stat timestamps while retaining HEAD blob identities, so later
source mutations preserve tracked/dirty/untracked semantics. Reflogs and hooks are
excluded because the selected read-only SCM/version operations do not consume
them. The snapshot is re-discovered and hashed before preparation publication.
SCM queries remain disabled when the action has no declared `.git/HEAD`, preventing
copied fixtures from discovering an enclosing checkout. They remain enabled for
this declared snapshot, and the actual MinVer child process uses staged package
payloads and the declared SDK.

The Git contract rejects worktree indirection, alternates, split indexes, config
includes, unsupported config keys/extensions and symlinked metadata roots, files
or directories. It does not claim general Git layout/config support or complete
host closure. A source checkout using those forms needs a supported standalone
snapshot, rather than silently reading outside the declared inputs.

## Final integration validation

Fourteen acceptance contract tests pass, including actual C# Git discovery and
negative checks for external config, unsupported layouts, symlinked directories
and dangling Git indirection. Two analyzer-payload integrity tests and two package
pin-policy tests pass; the optional acquired-Serilog policy test was not selected.
Fifteen restore-semantics tests pass, including three central-package management
cases. The ordinary PrivateAssets regression passes all four modes. Owned .NET
builds and formatter verification pass, with five code-style enforcement tests;
the action-runner contract/process executable also passes. The final legacy
five-project generator cold smoke passes all five native sandbox actions at
`/private/tmp/spectre-final-generator-smoke-2/report.json`. The first smoke attempt
stopped at missing local Buildifier; after supplying the already-pinned binary,
the rerun passed. `bash scripts/check.sh` passes tool/version, shell and tracked
Starlark checks. `git diff --check` passes. Earlier 35-case framework-track results remain prerequisite
evidence and are not presented as rerun on this final integration.

## Remaining scope

This is one selected Release graph on native macOS. Full Spectre upstream tests,
other Console target frameworks, arbitrary central-package overrides/transitive
pinning, broader Git histories/layouts, RID/native package behavior, Linux execution
and independent remote workers remain separate. The shallow/no-tags source
baseline must not be presented as release-version qualification with full history.
The first attempted removal deleted the required Ascii spinner; ordinary MSBuild
correctly failed CS0117. The passing removal case uses Dots and does not weaken
ordinary compilation or generator failure handling.
