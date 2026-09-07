# R02 generated-graph managed-package cache

The full cache probe adds pinned managed packages on Left to the package-free
diamond and retains every R01 selective-invalidation and recovery control.
Run the full suite separately:

```sh
python3 -m unittest discover -s tests/graph_cache_full -v
python3 tools/probe_graph_cache.py --output artifacts/graph-package-cache-probe
```

The original focused suite still runs with
`python3 -m unittest discover -s tests/graph_cache -v`; its probe explicitly
selects `--package-free`. Full reports identify the
`R02-managed-package-cache` scope. Compile markers contain normalized relative
project paths; action-report `compiledProjects` remains stem-based for existing
consumers.

## Package and failure evidence

The probe builds the existing deterministic `binary_inputs.Packages` fixture
outside Bazel actions and writes all archive SHA-256 pins to `package-pins.json`.
Each restored source copy uses a local `.feed` with the same relative NuGet
configuration. Only Left directly references exact `RulesMsbuild.Binary` versions
`[1.0.0]` and `[1.0.1]`; the package depends on `RulesMsbuild.Leaf`. Observable output
maps the actual package result to `package-v1` or `package-v2`.

Separate ordinary MSBuild static-graph builds provide package v1/v2 output
oracles. The probe deletes package preparation sources before the cold and
upgrade Bazel builds, preserves both exported graphs and retained runtime DLLs,
and verifies the staged archive hashes against the original fixture pins.
Tests recompute those archive/payload hashes, require package inputs on Left and
App only, and check that upgrades execute only Left and App.

Package recovery uses a separate package disk cache and deletes the output base
and generated producer outputs. Relocation restores a fresh consumer, deletes
both producer and consumer preparation directories before building, and runs
App from the recovered bundle. Both cases require four disk hits, zero project
executions and complete bundle-byte/executable-bit equality with package cold.

Each negative case independently restores, exports, prepares and warms a valid
package baseline. It then changes one source, reference or declared package DLL
and invokes the real preparation CLI with the original manifest. The report
parses the actual diagnostic from captured output and records the real exit
status and publication-path existence. It never fabricates expected diagnostic
codes. Tests require missing source/package, corrupt package, stale project
graph and stale restore rejection; original manifest hashes must remain intact
and logs must contain no subject compile markers.

## Validation and limits

On native macOS ARM64 with the pinned Nix SDK 10.0.100 and Bazel 8.4.2,
`python3 -m unittest discover -s tests/graph_cache_full -v` passed all 12 tests.
The run used package production commit `f7eaf83` (locally cherry-picked as
`e2df71e`) and the `configure` fixture helper from the parallel PrivateAssets
track (`5eec845`). Retained evidence:
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/msbuild-graph-cache-4cnhk8e8/probe`.

| Case | Native project executions | Disk hits | App output |
| --- | --- | --- | --- |
| Package cold | All four | 0 | `shared-v1:left/package-v1|shared-v1:right` |
| Package upgrade | Left, App | 0 | `shared-v1:left/package-v2|shared-v1:right` |
| Package clean recovery | None | 4 | Package v1 baseline |
| Package relocation | None | 4 | Package v1 baseline |

Both recovered bundle digests matched package cold, including every retained
file and executable bit. Native actions reported `darwin-sandbox` and local-only
execution/cache flags. All five failure controls returned nonzero with the
specified diagnostic, unchanged original manifest, no new publication and no
subject compilation. All inherited package-free assertions passed in the same
run. Linux validation remains a CI gate. This cache contract covers the ordinary
managed ref/lib package flow; PrivateAssets variants are measured by the
separate R02 controls. RID/native assets, arbitrary NuGet targets, remote reuse,
full host closure and cross-platform cache portability remain outside this
claim. Concurrent runs establish correctness, not performance.

## Stale metadata publication guards

Review reproduced a stale PrivateAssets escape: after an omitted-metadata
restore, changing Left to `PrivateAssets="all"` and re-exporting without restore
published a plan that still gave App both package identities. A correct restore
removed both from App. The reproduction is retained at
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/r02-stale-privateassets-review-5ze3zhfp`.
The version-only preflight did not establish restore freshness for this supported
metadata change.

The full probe now adds three independently warmed controls: changed
PrivateAssets, a changed exact version inside the MSBuild XML namespace, and an
unpinned version inside that namespace. Each attempts both a fresh export without
restore and direct preparation with the previous manifest. Expected diagnostics
are `stale-restore`, `stale-restore` and `unsupported-package`, respectively.
Neither attempt may publish a fresh graph or replacement plan, and no Bazel
invocation follows either rejection.

Each control retains the mutated project, both raw rejection logs, original
manifest hash, and every regular file in the previously published preparation.
Before/after plan snapshots include content hashes and executable flags; the
suite checks their equality and independently hashes retained bytes. A recorded
Bazel invocation ledger must remain unchanged after the warm baseline. These
checks prevent reporting a rejected replacement while silently consuming or
damaging an earlier plan.

The additional guard method brings full-suite coverage to 13 test methods.
Python syntax and whitespace checks pass. The new controls await the production
restore-semantic fix and an integrated native run; the earlier 12-test passing
record above predates these additional guards.

## Integrated review-fix acceptance

At `2407142`, all 13 full cache tests passed on native macOS ARM64 in 237.611
seconds, including every package-free control, managed-package upgrade, both
package recovery modes and the new stale-metadata publication guards. The seven
PrivateAssets/restore-semantics tests also passed on this revision. Commands used
the pinned Nix SDK/Bazel overrides and native `darwin-sandbox`. Evidence is retained
at `/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/msbuild-graph-cache-rloaltwq/probe`;
combined log: `/private/tmp/r02-full-final.log`. Linux acceptance remains pending
for the integrated package revision. Overlapping correctness runs are not
performance measurements.
