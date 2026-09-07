# First exported graph execution slice

Measured on macOS ARM64 on 2026-09-06 with the pinned Nix .NET SDK 10.0.100 and
Bazel 8.4.2. This is the first supported slice of roadmap milestone 2, not completion
of arbitrary configured graph execution.

The [contract](graph-execution-contract.md) and executable diamond acceptance were
committed first (`96192d8`). Before implementation,
`python3 -m unittest discover -s tests/graph_execution -v` failed with
`Milestone 2 graph execution is not implemented`, as intended.

## Measured result

```sh
# With RULES_MSBUILD_DOTNET_ROOT and RULES_MSBUILD_BAZEL set to the pinned Nix tools:
python3 -m unittest discover -s tests/graph_execution -v
```

All 15 tests passed in 23.638 seconds. Native Bazel acceptance required running
outside Codex's enclosing sandbox; inside it Bazel did not register darwin-sandbox.
The passing run retained darwin-sandbox, blocked network and no-remote requirements.

The independently restored diamond exported four nodes. Generated Bazel actions
compiled Shared, Left, Right and App exactly once each. Left and Right each replayed
Shared. App replayed Shared, Left and Right, receiving their verified artifact
bundles and public-API result metadata. No dependency was compiled inside a consumer.
Both ordinary isolated static-graph MSBuild and the generated Bazel result printed:

```text
shared-v1:left|shared-v1:right
```

Preparation was deleted before Bazel executed, and each action staged its own
workspace. This excludes accidental dependence on preparation bin/obj outputs.
A separate native root-project case without Directory.Build.props/targets also
passed and printed `root-project`. Thirteen lightweight rejection cases passed:
unsupported globals and Debug, output-layout changes, packages, missing nodes,
cycles, missing/escaping inputs, stale sources/imports/restores/traversal and
unsupported declared obj sources.

The probes retain `report.json`, `manifest.json`, baseline/build logs, generated
Bazel files, action execution logs, diagnostics and bundles in the supplied output
directory. Test-created evidence uses the `graph-execution-*` system temporary
prefix. Repeat independently with:

```sh
python3 tools/probe_graph_execution.py --output artifacts/graph-execution
python3 tools/probe_graph_execution.py --output artifacts/root-execution --root-project
```

## Integration checks

On the combined branch, with the same pinned Nix tool overrides, both existing
regression commands passed on macOS:

```sh
python3 -m unittest discover -s tests/e2e -p test_action_runner.py -v
python3 -m unittest discover -s tests/e2e -p test_msbuild_replay.py -v
```

The runner contracts passed (one unittest entry, 2.690 seconds). The legacy replay
probe passed (one unittest entry, 12.695 seconds), covering same-path and relocated
replay, App edits, Publish and eleven rejection controls. Before integration, all
12 unchanged graph-export tests passed locally, and `bash scripts/check.sh`
passed with the pinned tools. `git diff --check` passed after integration.

The new `.github/workflows/graph-execution.yml` runs exporter regression, runner
contracts and graph execution acceptance on Ubuntu 22.04, retaining logs/reports.
It had not been dispatched during initial implementation. The subsequent native
Linux result is recorded below.
At initial implementation the separate milestone 3 cache suite remained
intentionally red and was not part of the milestone 2 CI gate. The R01 workflow
now adds its package-free acceptance command; package cases remain R02 work.

## Boundary and remaining work

Only the `configuration=Release` net10.0 standard-output, package-free slice is
accepted. Different global properties and output contracts are rejected explicitly.
Managed package behavior proven by the old explicit adapter has not yet been
integrated into generated graph execution. Selective invalidation, graph mutation,
local disk-cache recovery and relocation need the milestone 3 experiments; this
probe records cold execution only. Full host/runtime closure, remote caching,
remote execution and cross-platform reuse remain unproven. The existing cold execution slice also passes native Linux CI as recorded below;
the additional R01 cache and handoff controls still need their own Linux runs.


## Native Linux execution baseline (R01)

On 2026-09-07 UTC (2026-09-06 Pacific), the existing workflow passed at commit
`6a14e1f853eac85c80ac2698c9788033484a88f9` in
[Actions run 34068495578](https://github.com/keegan-caruso/msbuild-bazel/actions/runs/34068495578),
on native Ubuntu 22.04 Linux x86-64 with setup-pinned .NET SDK 10.0.100 and
Bazel 8.4.2. The run finished at 00:04:01 UTC. This result was retrieved and
inspected from an already completed run, not newly dispatched by this track.

| Command | Observed result |
| --- | --- |
| `python3 -m unittest discover -s tests/graph -v` | 12 passed in 42.673 seconds |
| `bash scripts/dotnet.sh run --project tests/ActionRunner.Tests -c Release` | Action runner contract and process tests passed |
| `python3 -m unittest discover -s tests/graph_execution -v` | 15 passed in 70.888 seconds |

The downloaded
[configured-graph-execution-evidence artifact](https://github.com/keegan-caruso/msbuild-bazel/actions/runs/34068495578/artifacts/9999734509)
contains the diamond report at `graph-execution-am46ooc3/evidence/report.json`
and root-project report at `graph-execution-_tytroja/root/report.json`, together
with baseline, build and application logs. The upload records archive SHA-256
`84f9ab22e2c9c12728c639ba05fdff7a0533bccef3ac6e32147321f457fd671a`.
Retrieve these with:

```sh
gh run view 34068495578 --log
gh run download 34068495578 -n configured-graph-execution-evidence -D artifacts/linux-graph-execution
```

The diamond report records four cold `linux-sandbox` actions, each compiling
only its own project. Left and Right replay Shared; App replays Shared, Left and
Right. All four return zero, and baseline/generated App output is exactly
`shared-v1:left|shared-v1:right`. The root case also reports `linux-sandbox`,
one App compilation and `root-project` output. Both reports record preparation
workspace removal before execution. The thirteen preparation rejection tests
passed in the same job. There were no skipped acceptance cases.

The original artifact filter retained reports and text logs but omitted raw
`execution.json` and `manifest.json`. The reports and passing assertions support
the observed runner/replay result; independent raw execution-record auditing is
limited for this historical artifact. The workflow now retains those JSON files,
runs the existing public-API replay regression explicitly, and accepts R01 branch
pushes/manual dispatches. These workflow additions have not themselves run in
Linux CI yet. R01 handoff tests have a separate `tests/graph_handoff` discovery step with
retained logs and reports. The parallel cache track narrows `tests/graph_cache` to its
package-free R01 acceptance cases; the workflow now runs that discovery command
and retains its `msbuild-graph-cache-*` probe logs, JSON and per-case bundle
evidence so downloaded artifact hashes can be checked independently. These new gates
require the parallel implementations to be integrated before running.

This closes the existing-execution part of the `linux` work package. It does not
accept the new cache, input-discovery or interrupted-publication controls, the
full R01 local milestone, package-bearing generated graphs, remote reuse or full
host closure. Those require validation at their integrated implementation SHA.
