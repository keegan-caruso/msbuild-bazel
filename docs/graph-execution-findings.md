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
# With SPIKE_DOTNET_ROOT and SPIKE_BAZEL set to the pinned Nix tools:
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
It has not been dispatched in this session; adding CI is not Linux evidence.
The separate milestone 3 cache suite remains intentionally red and is not part
of the milestone 2 CI gate.

## Boundary and remaining work

Only the `configuration=Release` net10.0 standard-output, package-free slice is
accepted. Different global properties and output contracts are rejected explicitly.
Managed package behavior proven by the old explicit adapter has not yet been
integrated into generated graph execution. Selective invalidation, graph mutation,
local disk-cache recovery and relocation need the milestone 3 experiments; this
probe records cold execution only. Full host/runtime closure, remote caching,
remote execution and cross-platform reuse remain unproven. Linux acceptance has
not been run in this local session and must use CI.
